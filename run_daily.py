"""
run_daily.py - The orchestrator. Run this once per day (Task Scheduler does it for you).
Generates N videos: script -> voiceover -> captions -> background -> assemble -> upload.

Usage:
    python run_daily.py            # uses videos_per_day from config.json
    python run_daily.py --dry-run  # builds videos but does NOT upload (for testing)
"""
import argparse
import datetime as dt
import json
import os
import sys
import traceback

import re

import subprocess

try:
    import analyzer
    import winner_memory
    import boost
    import compilation
    import scriptgen
    import specials
    import tts
    import captions
    import visuals
    import assemble
except Exception as _imp_err:
    # An import-time failure (e.g. "ModuleNotFoundError: No module named 'google'" when the
    # scheduler uses the wrong Python) happens BEFORE main()'s crash handler, so without this
    # the scheduled run dies COMPLETELY SILENTLY - zero videos, no alert. Best-effort notify
    # using stdlib only (the heavy libs may be what's missing), write a marker, then re-raise.
    import traceback as _tb0, json as _json0, urllib.request as _ur0
    _msg0 = ("Hidden Logic FAILED TO START (import error - likely the scheduler is using a "
             "Python without the project's dependencies):\n\n" + _tb0.format_exc()[-1200:])
    try:
        with open("STARTUP_FAILED.txt", "w", encoding="utf-8") as _f0:
            _f0.write(_msg0)
    except Exception:
        pass
    try:
        with open("config.json", encoding="utf-8") as _cf0:
            _wh0 = _json0.load(_cf0).get("alert_webhook_url", "")
        if _wh0:
            _req0 = _ur0.Request(_wh0, data=_json0.dumps({"content": _msg0[:1800]}).encode(),
                                 headers={"Content-Type": "application/json"})
            _ur0.urlopen(_req0, timeout=10)
    except Exception:
        pass
    raise

CONFIG_FILE = "config.json"
LOG_FILE = "pipeline_log.txt"

# attention events collected during a run, surfaced in the end-of-run digest so you
# know about quota stress, repeated quality misses, and surrendered slots at a glance.
ATTENTION = []


def flag(msg: str):
    """Record an attention-worthy event for the digest (deduped)."""
    if msg not in ATTENTION:
        ATTENTION.append(msg)


def log(msg: str):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


INTERNAL_MARKERS = ("factcheck", "quality score", "quality_note", "review pass",
                    "era check", "issues_found", "[scriptgen]", "[tts]")


def _trim_title(title: str, max_len: int = 60) -> str:
    """Trim a title to <= max_len at WORD boundaries, preserving a trailing emoji.
    Never slices mid-word."""
    title = title.strip()
    if len(title) <= max_len:
        return title
    parts = title.split()
    emoji = ""
    if parts and not parts[-1].isascii():   # last token is an emoji
        emoji = parts[-1]
        body = " ".join(parts[:-1])
    else:
        body = title
    budget = max_len - (len(emoji) + 1 if emoji else 0)
    if len(body) > budget:
        out = ""
        for w in body.split():
            if out and len(out) + 1 + len(w) > budget:
                break
            out = (out + " " + w) if out else w
        body = out.rstrip(" ,:-–")
    return (body + (" " + emoji if emoji else "")).strip()


# Words that must NEVER become a hashtag even when they appear in the title. Hashtags
# should be concrete, searchable subjects (#supermarket, #airports, #psychology), not
# filler. Without this, the old title-word rule leaked junk tags like #noticing / #forever
# / #wait whenever the writer emitted a stopword tag that happened to be in the title.
HASHTAG_STOPWORDS = {
    "the", "a", "an", "your", "you", "my", "our", "us", "we", "i", "it", "its", "their",
    "them", "they", "this", "that", "these", "those", "is", "are", "was", "were", "be",
    "been", "being", "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "and", "or", "but", "so", "if", "then", "than", "as", "of", "to",
    "in", "on", "at", "for", "from", "with", "without", "about", "into", "always", "never",
    "really", "actually", "just", "very", "more", "most", "again", "still", "even", "only",
    "also", "ever", "forever", "now", "here", "there", "when", "where", "why", "how", "what",
    "who", "which", "while", "wait", "waiting", "notice", "noticing", "thing", "things",
    "stuff", "way", "ways", "reason", "reasons", "people", "someone", "everyone", "anything",
    "everything", "something", "really", "get", "got", "getting", "make", "makes", "making",
    "keep", "keeps", "come", "came", "go", "goes", "going", "one", "two", "every", "all",
}


# Fixed channel "about" blurb appended to EVERY video description. This gives YouTube a
# consistent, keyword-rich signal about what the channel is (search categorization + channel
# identity) and tells viewers what to expect. It's the same on every video by design.
CHANNEL_BLURB = (
    "Hidden Logic reveals the hidden reasons behind everyday things you never stop to question. "
    "New Shorts every day."
)


def build_seo_description(hook_desc: str, title: str = "", script: str = "") -> str:
    """Assemble the final, SEO-structured video description from the per-video hook description.

    Structure (what YouTube's search/recommendation reads, and what a viewer sees):
      1. The per-video hook/explanation (specific, concrete - the LLM-written line). This is the
         most important part: it carries the video's actual searchable keywords (the subject,
         the mechanism, the everyday frustration).
      2. A blank line, then the fixed CHANNEL_BLURB (consistent channel identity + niche keywords).

    The visible #hashtags are appended later by upload.upload(), so they are NOT added here.
    We keep the whole thing well under YouTube's limit and never cut a sentence mid-word.
    """
    hook_desc = (hook_desc or "").strip()
    # Make sure the hook ends on a complete sentence (the old descriptions sometimes cut off
    # mid-thought, e.g. "The five-second countdown?" with nothing after - which wastes the
    # SEO real estate and reads as broken).
    if hook_desc and hook_desc[-1] not in ".!?":
        # try to trim back to the last complete sentence; if there isn't one, add a period
        cut = max(hook_desc.rfind("."), hook_desc.rfind("!"), hook_desc.rfind("?"))
        if cut >= len(hook_desc) * 0.4:
            hook_desc = hook_desc[:cut + 1].strip()
        else:
            hook_desc = hook_desc.rstrip(" ,;:-–—") + "."
    # Compose: hook + blank line + channel blurb. Cap so hook+blurb+hashtags stay well under 1000.
    blurb = CHANNEL_BLURB
    max_hook = 1000 - len(blurb) - 4  # room for the "\n\n" join and the hashtags upload adds
    if len(hook_desc) > max_hook:
        hook_desc = hook_desc[:max_hook].rstrip()
        cut = max(hook_desc.rfind("."), hook_desc.rfind("!"), hook_desc.rfind("?"))
        if cut > 0:
            hook_desc = hook_desc[:cut + 1]
    parts = [p for p in (hook_desc, blurb) if p]
    return "\n\n".join(parts)


def _trim_comment(text: str, max_len: int = 240) -> str:
    """Trim a pinned first-comment to <= max_len WITHOUT slicing mid-word. Prefers ending
    at a sentence boundary; otherwise ends at a word boundary with an ellipsis. The old
    `fc[:150]` hard-sliced mid-word (e.g. '...feels like yo')."""
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    window = text[:max_len]
    # prefer the last full sentence that fits
    ends = list(re.finditer(r"[.!?](?:\s|$)", window))
    if ends and ends[-1].end() >= max_len * 0.5:
        return window[:ends[-1].end()].strip()
    # otherwise cut at the last word boundary and signal continuation
    if " " in window:
        window = window[:window.rfind(" ")]
    return window.rstrip(" ,;:-–—") + "…"


def sanitize_meta(meta: dict) -> dict:
    """Last line of defense before anything goes public: no internal pipeline
    text, no empty descriptions, max 4 clean hashtags, sane title."""
    script = meta.get("script", "")
    title = (meta.get("title") or "").strip()
    if not title:
        title = (meta.get("topic", "Hidden Logic") or "Hidden Logic")[:90]
    meta["title"] = title[:95]

    # We use the description generated by the LLM (which is instructed to be specific and concrete).
    # If it failed to generate one, fallback to the first two sentences of the script.
    desc = (meta.get("description") or "").strip()
    if not desc or any(m in desc.lower() for m in INTERNAL_MARKERS):
        sentences = re.split(r"(?<=[.!?])\s+", script)
        desc = " ".join(sentences[:2]).strip() or "The answer isn't what you think."

    # Build the final SEO-structured description: the per-video hook (carries the video's real
    # searchable keywords) + the fixed channel blurb (consistent channel identity + niche terms).
    # Visible #hashtags are appended later by upload.upload(), so they're not added here.
    meta["description"] = build_seo_description(desc, title=meta.get("title", ""), script=script)

    tags = []
    for t in meta.get("hashtags", []):
        t = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#"))
        if len(t) > 1 and t.lower() not in [x.lower() for x in tags]:
            tags.append(t)
    if "#shorts" not in [t.lower() for t in tags]:
        tags.insert(0, "#shorts")

    # SUBJECT TAG FROM TITLE: the LLM's hashtag can go stale when the review rewrites
    # the script to a new subject (e.g. a pre-2000 Pele topic gets reworked to Messi,
    # but the tag stays #pele). The title's subject (before the colon) is always
    # correct, so derive the authoritative subject tag from it and drop any tag that
    # clearly belongs to a different person/nation than the title is about.
    def _subject_tag_from_title(title: str) -> str:
        import unicodedata
        lead = title.split(":")[0] if ":" in title else title
        lead = re.sub(r"\s*#.*$", "", lead)
        # strip accents so tags are clean ascii (Mbappé -> mbappe)
        lead = "".join(c for c in unicodedata.normalize("NFKD", lead)
                       if not unicodedata.combining(c))
        # drop qualifiers and years
        lead = re.sub(r"\b\d{2,4}\b", "", lead, flags=re.I)
        lead = lead.replace("'", "").replace("\u2019", "")
        words = re.findall(r"[A-Za-z]+", lead)
        if not words:
            return ""
        # pick the most subject-like word: the last non-stopword of length >= 4. This
        # avoids deriving junk subject tags like #noticing / #wait from trailing fillers.
        candidates = [w for w in words if w.lower() not in HASHTAG_STOPWORDS and len(w) >= 4]
        if not candidates:
            return ""
        token = candidates[-1].lower()
        return "#" + token if len(token) >= 3 else ""
    subj_tag = _subject_tag_from_title(meta.get("title", ""))
    title_l = re.sub(r"[^\w\s]", "", meta.get("title", "")).lower()
    title_words = set(title_l.split())
    GENERIC = {"#shorts", "#hiddenlogic", "#brainfacts", "#psychology", "#fyp"}
    # Keep a tag only if it is a generic channel tag, OR a concrete subject word that
    # actually appears in the title (word-boundary match, not substring) AND is not a
    # filler stopword. This kills junk leaks like #noticing / #forever / #wait while still
    # keeping real subject tags (#supermarket, #airports).
    cleaned = []
    for t in tags:
        tl = t.lower()
        core = tl.lstrip("#")
        if tl in GENERIC:
            cleaned.append(t)
        elif core in title_words and core not in HASHTAG_STOPWORDS and len(core) >= 3:
            cleaned.append(t)
    if subj_tag and len(subj_tag) > 3 and subj_tag.lower() not in [c.lower() for c in cleaned]:
        cleaned.insert(1 if cleaned and cleaned[0].lower() == "#shorts" else 0, subj_tag)
    tags = cleaned
    meta["hashtags"] = tags[:3]

    # in-title hashtags: the video's OWN subject tags (relevant only) + evergreen niche tags.
    EVERGREEN = ["#hiddenlogic", "#psychology"]
    subject_tags = [t for t in tags if t.lower() not in ("#shorts", "#hiddenlogic")
                    and t.lower() not in [e.lower() for e in EVERGREEN]]
    title_tags = []
    for t in subject_tags[:1] + EVERGREEN:  # 1 subject tag + 2 evergreen = 3 (YouTube shows 3)
        if t.lower() not in [x.lower() for x in title_tags]:
            title_tags.append(t)
    title_tags = title_tags[:3]
    base_title = _trim_title(meta["title"], 60)  # tight, word-boundary, emoji preserved
    # Keep titles clean and premium without appending trailing hashtags
    meta["title"] = base_title[:100]
    # ensure those tags are also in the description hashtag list (YouTube needs them there too)
    for t in reversed(title_tags):
        if t.lower() not in [x.lower() for x in meta["hashtags"]]:
            meta["hashtags"].insert(0, t)
    meta["hashtags"] = meta["hashtags"][:3]
    meta["franchise"] = None

    # HIDDEN STUDIO TAGS (separate from visible hashtags): the research wants 5-8 precise,
    # broad-to-specific tags for search categorization. These are invisible to viewers, so
    # we can include evergreen channel tags + this video's subject without cluttering the
    # description. Subject tags first (most specific), then evergreen niche tags.
    EVERGREEN_TAGS = ["hidden logic", "psychology", "brain facts", "human behavior",
                      "cognitive bias", "mind tricks", "memory", "attention"]
    # Primary tags = the model's specific search phrases (real queries people type),
    # which fixes the "random irrelevant search terms" problem. Subject + evergreen fill in.
    seo_kw = [str(k).strip().lstrip("#") for k in (meta.get("seo_keywords") or []) if str(k).strip()]
    subj_words = [t.lstrip("#") for t in meta["hashtags"]
                  if t.lower() not in ("#shorts", "#hiddenlogic", "#psychology", "#hiddenreasons")]
    upload_tags = []
    for t in seo_kw + subj_words + EVERGREEN_TAGS:
        tl = t.lower()
        if tl and tl not in [x.lower() for x in upload_tags]:
            upload_tags.append(t)
    meta["tags"] = upload_tags[:15]  # specific search phrases first, then niche fill

    fc = (meta.get("first_comment") or "").strip()
    if any(m in fc.lower() for m in INTERNAL_MARKERS):
        fc = ""
    meta["first_comment"] = _trim_comment(fc, 240)
    return meta


def _parse_slot(s) -> tuple | None:
    """Parse a publish-slot time string into (hour, minute). Tolerant of common formats:
    '15:00', '15', '9:5', ' 21:30 '. Returns None for anything unparseable (caller skips it)
    so one bad config entry never crashes the whole run."""
    try:
        txt = str(s).strip()
        if not txt:
            return None
        parts = txt.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
        if 0 <= h <= 23 and 0 <= m <= 59:
            return (h, m)
    except Exception:
        pass
    return None


def compute_publish_slots(cfg: dict, n: int) -> list:
    """Build exact Singapore publication slots, independent of runner timezone."""
    slots = cfg.get("publish_slots")
    if not slots:
        return []
    from zoneinfo import ZoneInfo
    now = dt.datetime.now(ZoneInfo(cfg.get('timezone','Asia/Singapore')))
    candidates = []
    for day in range(8):
        for s in slots:
            parsed = _parse_slot(s)
            if not parsed:
                continue  # skip malformed entries like "15" missing minutes, bad text, etc.
            h, m = parsed
            t = (now + dt.timedelta(days=day)).replace(hour=h, minute=m, second=0, microsecond=0)
            if t > now + dt.timedelta(minutes=3):
                candidates.append(t)
    candidates.sort()  # chronological, so an overnight slot is never skipped
    return candidates[:n]


def _resolve_rolling(slots: list) -> list:
    """Resolve a forward-rolling grid like ['15:00','19:00','03:00'] into actual
    datetimes IN ORDER: each slot is its next future occurrence at or after the
    previous one, so an overnight wrap stays in sequence (not re-sorted to the top)."""
    now = dt.datetime.now()
    out = []
    cursor = now
    for s in slots:
        parsed = _parse_slot(s)
        if not parsed:
            continue  # skip malformed slot entries instead of crashing
        h, m = parsed
        t = cursor.replace(hour=h, minute=m, second=0, microsecond=0)
        while t <= cursor + dt.timedelta(minutes=3):
            t += dt.timedelta(days=1)
        out.append(t)
        cursor = t
    return out


def _to_utc_iso(local_dt) -> str:
    return local_dt.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


PENDING_COMMENTS_FILE = "pending_comments.json"


def _queue_pending_comment(video_id: str, text: str, publish_at: str, kind: str = "comment"):
    """Save an engagement action (first-comment or self-like) to run later, once the scheduled
    video goes public. YouTube rejects comments on still-private scheduled videos (and self-likes
    on them are unreliable), so we stash both here and flush on a later run."""
    pend = []
    if os.path.exists(PENDING_COMMENTS_FILE):
        try:
            with open(PENDING_COMMENTS_FILE, encoding="utf-8") as f:
                pend = json.load(f)
        except Exception:
            pend = []
    # avoid duplicates for the same (video, action-kind)
    if not any(p.get("video_id") == video_id and p.get("kind", "comment") == kind for p in pend):
        pend.append({"video_id": video_id, "text": text, "publish_at": publish_at, "kind": kind})
        with open(PENDING_COMMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(pend, f, indent=2, ensure_ascii=False)


def _flush_pending_comments(log=print):
    """At the start of a run, try to post any queued first-comments whose videos should now be
    public (publish time has passed). Successfully posted ones are removed; ones that still fail
    (video not live yet) stay queued for next time. Fully non-fatal."""
    if not os.path.exists(PENDING_COMMENTS_FILE):
        return
    try:
        with open(PENDING_COMMENTS_FILE, encoding="utf-8") as f:
            pend = json.load(f)
    except Exception:
        return
    if not pend:
        return
    import upload
    now_utc = dt.datetime.now(dt.timezone.utc)
    still_pending = []
    posted = 0
    for p in pend:
        # only attempt once the scheduled publish time has passed (video should be public)
        try:
            pub = p.get("publish_at")
            ready = True
            if pub:
                pub_dt = dt.datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
                ready = now_utc >= pub_dt
            if not ready:
                still_pending.append(p)
                continue
            if p.get("kind", "comment") == "like":
                upload.post_like(p["video_id"])
            else:
                upload.post_comment(p["video_id"], p["text"])
            posted += 1
        except Exception:
            # video may still not be public, or transient error - keep it for next run
            still_pending.append(p)
    if posted:
        log(f"Posted {posted} queued first-comment(s) on now-live videos.")
    try:
        with open(PENDING_COMMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(still_pending, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _classify_mood(meta: dict) -> str:
    """Infer the video's emotional tone and map it to ONE of the 7 music mood folders the
    channel uses: epic, cool, dramatic, lofi, upbeat, inspiring, peaceful.
    Uses title + script + taxonomy keyword signals."""
    text = " ".join([
        str(meta.get("title", "")),
        str(meta.get("script", ""))[:400],
        str(meta.get("taxonomy", "")),
        str(meta.get("visual_thesis", "")),
    ]).lower()

    # ordered by priority - first match wins, strongest/most-specific signals first
    # DRAMATIC: being manipulated, dark patterns, "evil" reveals - high tension
    if any(c in text for c in ("manipulat", "trick", "exploit", "addict", "trap", "scam",
                               "dark", "evil", "steal", "control", "watching you",
                               "without you", "designed to make", "casino")):
        return "dramatic"
    # EPIC: sports, competition, big-stakes, world cup / F1 energy
    if any(c in text for c in ("goal", "score", "win", "match", "world cup", "penalty",
                               "goalkeeper", "f1", "race", "stadium", "champion", "final",
                               "team", "player", "soccer")):
        return "epic"
    # UPBEAT: food, fun, light everyday quirks
    if any(c in text for c in ("food", "drink", "mcdonald", "snack", "taste", "popcorn",
                               "candy", "fast food", "buffet", "fun", "happy", "coffee")):
        return "upbeat"
    # INSPIRING: clever design, "smart" reveals, how things cleverly work
    if any(c in text for c in ("design", "clever", "genius", "brilliant", "engineer",
                               "architect", "smart", "ingenious", "invented")):
        return "inspiring"
    # PEACEFUL: calm everyday settings, hotels, sleep, quiet routines
    if any(c in text for c in ("hotel", "sleep", "calm", "quiet", "relax", "morning",
                               "pillow", "bed", "shower", "rest")):
        return "peaceful"
    # COOL: shopping, pricing psychology, modern/tech, slick consumer stuff
    if any(c in text for c in ("shop", "store", "price", "pricing", "supermarket", "mall",
                               "app", "phone", "tech", "online", "checkout", "cart")):
        return "cool"
    # LOFI default: the channel's core "huh, interesting" mellow curiosity tone
    return "lofi"


def _pick_music_by_mood(music_dir: str, meta: dict, log=print):
    """Pick a track from a mood-matching subfolder if mood subfolders exist; otherwise pick
    from the flat folder (so existing setups keep working). Mood subfolders are matched by
    name keyword. Fully non-fatal - music never blocks a build."""
    import random
    exts = (".mp3", ".m4a", ".wav", ".ogg")
    try:
        mood = _classify_mood(meta)
        # Folder-name keywords for each mood. The first alias is the exact folder name; the
        # rest are fallbacks to a RELATED mood folder if the exact one is empty/missing, so a
        # video always gets tonally-appropriate music even if you haven't filled every folder.
        mood_aliases = {
            "epic":      ("epic", "dramatic", "inspiring"),
            "dramatic":  ("dramatic", "epic", "cool"),
            "cool":      ("cool", "lofi", "upbeat"),
            "lofi":      ("lofi", "peaceful", "cool"),
            "upbeat":    ("upbeat", "cool", "inspiring"),
            "inspiring": ("inspiring", "epic", "upbeat"),
            "peaceful":  ("peaceful", "lofi", "cool"),
        }
        subdirs = [d for d in os.listdir(music_dir)
                   if os.path.isdir(os.path.join(music_dir, d))]
        chosen_dir = None
        tracks = []
        if subdirs:
            # try each alias in PRIORITY order (exact mood first, then related fallbacks);
            # accept the first folder that both matches AND actually contains tracks.
            for alias in mood_aliases.get(mood, (mood,)):
                for d in subdirs:
                    if alias in d.lower():
                        cand = os.path.join(music_dir, d)
                        cand_tracks = [os.path.join(cand, f) for f in os.listdir(cand)
                                       if f.lower().endswith(exts)]
                        if cand_tracks:
                            chosen_dir, tracks = cand, cand_tracks
                            break
                if chosen_dir:
                    break
        if chosen_dir:
            log(f"Music mood: {mood} -> '{os.path.basename(chosen_dir)}'")
        if not tracks:
            for root, _dirs, files in os.walk(music_dir):
                for f in files:
                    if f.lower().endswith(exts):
                        tracks.append(os.path.join(root, f))
            if chosen_dir is None and subdirs:
                log(f"Music mood: {mood} (no matching mood folder - using full library)")
        return random.choice(tracks) if tracks else None
    except Exception as e:
        log(f"music mood pick failed (non-fatal, using random): {e}")
        try:
            tracks = [os.path.join(music_dir, f) for f in os.listdir(music_dir)
                      if f.lower().endswith(exts)]
            return random.choice(tracks) if tracks else None
        except Exception:
            return None


def make_one(cfg: dict, workdir: str, dry_run: bool, publish_at: str | None = None,
             topic: str | None = None, strict_topic_lock: bool = False, generate_only: bool = False) -> str | None | dict:
    os.makedirs(workdir, exist_ok=True)
    scriptgen.PROVIDER = cfg.get("llm_provider", "gemini")
    scriptgen.MIN_SCORE = float(cfg.get("min_quality", 8))
    scriptgen.MAX_ATTEMPTS = int(cfg.get("max_attempts_per_video", 8))
    scriptgen.QUALITY_FLOOR = float(cfg.get("quality_floor", 6))
    scriptgen.TREND_WINDOW = cfg.get("trend_window", "now 1-d")
    import random as _rnd
    brief_hint = ""
    if topic is None and _rnd.random() > 0.30:  # 70% exploit the data, 30% explore freely
        brief_hint = analyzer.brief_prompt_snippet()
        try:
            brief_hint += analyzer.cached_retention_insight(cfg, log)
        except Exception:
            pass
    bench = ""
    try:
        bench = analyzer.cached_rater_benchmark(cfg, log)
    except Exception:
        bench = ""
    # A/B SCRIPT TEST: when cfg "script_ab" is on, randomly assign each video to variant
    # A (current prompt) or B (current + modern-mirror + hidden-truth techniques) so we can
    # compare retention before committing. Off by default = always A (no behavior change).
    if cfg.get("script_ab"):
        variant = _rnd.choice(["A", "B"])
    else:
        variant = cfg.get("script_variant", "A")  # allow forcing "B" once proven
    # NO LIVE DATA REQUIRED FOR EVERGREEN
    meta = sanitize_meta(scriptgen.generate(cfg.get("gemini_api_key", ""), topic=topic,
                                            extra_guidance=brief_hint, rater_benchmark=bench,
                                            variant=variant, strict_topic_lock=strict_topic_lock,
                                            publish_at=publish_at))
    meta["variant"] = variant
    clash = boost.is_duplicate_title(meta["title"])
    if clash and not topic:
        log(f"DUPLICATE GUARD: '{meta['title']}' matches existing '{clash}', regenerating")
        meta = sanitize_meta(scriptgen.generate(cfg.get("gemini_api_key", ""), variant=variant, publish_at=publish_at))
        meta["variant"] = variant
        clash = boost.is_duplicate_title(meta["title"])
        if clash:
            flag(f"A slot was dropped - couldn't avoid duplicating '{clash[:50]}'")
            raise RuntimeError(f"DUPLICATE GUARD: still clashing with '{clash}', surrendering slot")
    log(f"Topic: {meta['topic']}")
    log(f"Series: {meta.get('series', 'n/a')}")
    log(f"Title: {meta['title']}")
    log(f"Factcheck: {meta.get('factcheck', 'n/a')}")
    log(f"Topic Fidelity: {meta.get('topic_fidelity', 'n/a')}/10")
    log(f"Subject Retention: {meta.get('subject_retention', 'n/a')}/10")

    voice = os.path.join(workdir, "voice.mp3")
    timings = os.path.join(workdir, "timings.json")
    ass = os.path.join(workdir, "captions.ass")
    out = os.path.join(workdir, "short.mp4")

    import editorial_media
    # Both entry points require a complete first-draft production brief. Never
    # patch missing visual direction with an unrelated last-minute graphic.
    from production_brief import media_metadata
    from credible.storyboard import validate_storyboard
    meta = media_metadata(meta)
    validate_storyboard(meta.get('storyboard'))
    editorial_media.synthesize(meta, workdir, cfg)
    edit = editorial_media.render(meta, workdir, cfg)
    meta["sentence_scene_durations"] = [s["end"]-s["start"] for s in edit["scenes"]]
    meta["edit"] = edit
    log(f"Built {out} with distinct footage and a measured explanation scene")

    with open(os.path.join(workdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if generate_only:
        log("Generate only mode: skipping upload and cleanup.")
        return {"workdir": workdir, "predicted_views_score": meta.get("predicted_views_score", 0), "meta": meta, "topic": meta.get("topic", "")}

    if dry_run:
        log("Dry run: skipping upload")
        return {"url": "https://youtube.com/watch?v=dryrun", "title": meta.get("title", ""),
                "publish_at": publish_at, "topic": meta.get("topic", ""),
                "quality_score": meta.get("quality_score")}

    import upload
    url = upload.upload(out, meta["title"], meta["description"], meta["hashtags"],
                        publish_at=publish_at, meta_tags=meta.get("tags"))
    log(f"Uploaded: {url}" + (f" (publishes {publish_at})" if publish_at else ""))
    try:
        import video_context
        video_context.save_context(url.rsplit("/", 1)[-1].split("=")[-1], meta)
    except Exception as e:
        log(f"video_context save skipped (non-fatal): {e}")
    # record which A/B variant this video used, keyed by video id, so retention can be
    # compared later (see ab_report.py). Non-fatal; never blocks the pipeline.
    try:
        vid = url.rsplit("/", 1)[-1]
        ab_path = "ab_log.json"
        ab = {}
        if os.path.exists(ab_path):
            with open(ab_path) as f:
                ab = json.load(f)
        taxonomy = meta.get("taxonomy", "")
        subcluster = taxonomy.split("/")[1] if "/" in taxonomy else ""
        # merge (not replace) so any metrics analytics_poll already wrote for this id
        # (avd, stayed_to_watch, views_first_24h, ...) are preserved on a re-write.
        ab[vid] = {**ab.get(vid, {}),
            "variant": meta.get("variant", "A"),
            "title": meta.get("title", ""),
            "date": dt.date.today().isoformat(),
            "publish_at": publish_at,
            "cluster": meta.get("cluster"),
            "topic": meta.get("topic", ""),
            "subcluster": subcluster,
            "hook_type": meta.get("hook_type", ""),
            "series": meta.get("series", ""),
            "predicted_views_score": meta.get("predicted_views_score", 0.0),
            "retention_prediction": meta.get("retention_prediction", 0.0),
            "first_frame_score": meta.get("first_frame_score", 0.0),
            "viewer_identity_score": meta.get("viewer_identity_score", 0.0),
            "visual_thesis": meta.get("visual_thesis", ""),
            "first_frame_description": meta.get("first_frame_description", "")
        }
        with open(ab_path, "w") as f:
            json.dump(ab, f, indent=2)
    except Exception as e:
        log(f"ab_log write skipped (non-fatal): {e}")
    # PLAYLISTS (subscribe/binge driver): group each video into its series playlist on YouTube.
    # When a new viewer finishes one video and sees "Airport Logic - 14 videos", that "there's a
    # whole series of this exact thing" feeling is one of the strongest reasons to subscribe -
    # which is exactly the reason a self-contained Shorts format otherwise lacks. Non-fatal.
    try:
        series_name = meta.get("series", "").strip()
        if series_name and url and not dry_run:
            vid_id = url.rsplit("/", 1)[-1]
            desc = f"{series_name}: the hidden psychology and design behind everyday things. New videos regularly."
            ok = upload.add_to_playlist(vid_id, series_name, desc)
            log(f"Playlist: {'added to' if ok else 'could not add to'} '{series_name}'")
    except Exception as e:
        log(f"playlist add skipped (non-fatal): {e}")
    try:
        # By default we do NOT keep a local copy of the video (saves disk). Set
        # "keep_local_copy": true in config.json if you ever want an exports/ archive.
        exp = os.path.join("exports", dt.date.today().isoformat())
        os.makedirs(exp, exist_ok=True)
        if cfg.get("keep_local_copy"):
            import shutil as _sh
            _sh.copy(out, os.path.join(exp, re.sub(r"[^\w ]", "", meta["title"])[:60].strip() + ".mp4"))
        # always keep the tiny text log of what was posted (titles + hashtags)
        with open(os.path.join(exp, "captions.txt"), "a", encoding="utf-8") as f:
            f.write(meta["title"] + "\n" + " ".join(meta["hashtags"]) + "\n\n")
    except Exception as e:
        log(f"export log failed (non-fatal): {e}")
    video_id = url.rsplit("/", 1)[-1]
    try:
        cover = os.path.join(workdir, "cover.jpg")
        photo = None
        try:
            photo = visuals.fetch_thumbnail_photo(
                cfg.get("pexels_api_key", ""), meta.get("broll_keywords", []), workdir)
        except Exception:
            photo = None
        # base image: the stock stock photo, else a frame from the video. Try a few
        # timestamps and keep the brightest, so we never hand the thumbnail a black frame
        # (videos can open on a dark/loop frame). The thumbnail module also has its own
        # black-detection fallback as a final guard.
        base_img = photo
        if not base_img:
            base_img = os.path.join(workdir, "frame.jpg")
            best_frame, best_bright = None, -1
            for ts in ("2.0", "3.5", "5.0", "1.2"):
                cand = os.path.join(workdir, f"frame_{ts}.jpg")
                try:
                    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", ts, "-i", out,
                                    "-frames:v", "1", "-q:v", "2", cand],
                                   check=True, timeout=60)
                    from PIL import Image as _PILImage
                    sm = _PILImage.open(cand).convert("RGB").resize((32, 32))
                    bright = sum(sum(p) for p in sm.getdata()) / (32 * 32 * 3)
                    if bright > best_bright:
                        best_bright, best_frame = bright, cand
                except Exception:
                    continue
            if best_frame:
                base_img = best_frame
        made = False
        try:
            import thumbnail as _thumb       # PIL hype design
            _thumb.make_thumbnail(base_img, cover, meta.get("title", ""))
            made = True
        except Exception as e:
            log(f"hype thumbnail failed, using simple overlay ({e})")
        if not made:
            _make_thumbnail(out, cover, meta.get("title", ""), bg_photo=photo)
        # Generation and application are separate concerns: the file can render fine but
        # YouTube can still refuse to APPLY it (unverified channel = 403). Surface that
        # clearly and flag it for the digest so it doesn't silently keep happening.
        try:
            upload.set_thumbnail(video_id, cover)
            log("Thumbnail applied to video")
        except Exception as e:
            log(f"THUMBNAIL NOT APPLIED: {e}")
            flag(f"Thumbnail generated but YouTube refused to apply it: {e}")
    except Exception as e:
        log(f"Thumbnail step failed (non-fatal): {e}")
    src = "special" if topic else "pool"
    n = boost.record_upload(video_id, meta["title"], meta.get("topic", ""), source=src, metadata=meta)
    try:
        boost.localize(video_id, meta["title"], meta["description"])
        log(f"Localized to ES/PT (Daily Short #{n})")
    except Exception as e:
        log(f"Localization failed (non-fatal): {e}")
    try:
        _vid_for_like = url.rsplit("/", 1)[-1]
        if publish_at:
            # video is SCHEDULED (still private) - self-likes on private videos are unreliable
            # and were never retried, which is why scheduled videos ended up with no like.
            # Queue it; the flusher posts it on the next run once the video is live.
            _queue_pending_comment(_vid_for_like, "", publish_at, kind="like")
            log("Queued self-like (posts when live)")
        else:
            upload.post_like(_vid_for_like)
            log("Self-liked the upload")
    except Exception as e:
        log(f"Self-like failed (non-fatal): {e}")
    if meta.get("first_comment"):
        vid_for_comment = url.rsplit("/", 1)[-1]
        if not publish_at:
            # video is public now - comment immediately
            try:
                upload.post_comment(vid_for_comment, meta["first_comment"])
                log(f"Seeded first comment: {meta['first_comment']}")
            except Exception as e:
                log(f"First comment failed (non-fatal): {e}")
        else:
            # video is SCHEDULED (still private) - YouTube won't accept a comment yet. Save it
            # to the pending queue; it gets posted automatically on the next run once the video
            # has gone public. This is why scheduled videos previously never got a first comment.
            try:
                _queue_pending_comment(vid_for_comment, meta["first_comment"], publish_at)
                log(f"Queued first comment for when video goes live: {meta['first_comment'][:60]}")
            except Exception as e:
                log(f"Could not queue pending comment (non-fatal): {e}")
    try:
        hook_text = ""
        script_text = meta.get("script", "")
        if script_text:
            first_sentence = script_text.replace("\n", ". ").split(". ")[0].strip()
            hook_text = first_sentence + ("." if not first_sentence.endswith((".", "?", "!")) else "")
        winner_memory.update_hook_library(
            title=meta.get("title", ""),
            hook_text=hook_text,
            hook_type=meta.get("hook_type", "explainer"),
            hook_structure=meta.get("hook_structure", ""),
            first_frame_description=meta.get("first_frame_description", ""),
            visual_thesis=meta.get("visual_thesis", "")
        )
    except Exception as e:
        log(f"Hook library update failed: {e}")

    # CLEANUP: the video is now safely on YouTube, so delete the whole working folder
    # (clips, audio, captions, the final mp4, thumbnail, frames) to free disk space.
    # Nothing downstream needs these files - the digest record below is just text.
    try:
        import shutil as _sh
        _sh.rmtree(workdir, ignore_errors=True)
        log("Cleaned up local files (video uploaded, nothing kept on disk)")
    except Exception as e:
        log(f"Cleanup skipped (non-fatal): {e}")
    # return a small digest record for the end-of-run summary alert
    return {"url": url, "title": meta.get("title", ""),
            "publish_at": publish_at, "topic": meta.get("topic", ""),
            "quality_score": meta.get("quality_score")}

def publish_draft(cfg: dict, workdir: str, dry_run: bool, publish_at: str | None = None, log=print) -> dict | None:
    """Takes a generated draft directory and runs the upload sequence."""
    meta_path = os.path.join(workdir, "meta.json")
    if not os.path.exists(meta_path):
        log(f"Draft {workdir} missing meta.json")
        return None
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    
    # We call make_one's second half essentially.
    # To avoid huge code duplication, we'll just re-run the upload logic. 
    # But for simplicity, we assume `make_one` can just be bypassed or we 
    # extract the logic. Since I don't want to duplicate 150 lines, 
    # I'll rely on the existing make_one logic if we passed an already built workdir.
    # Actually, we can just invoke the upload logic here.
    out = os.path.join(workdir, "short.mp4")
    if dry_run:
        log("Dry run: skipping upload")
        return {"url": "https://youtube.com/watch?v=dryrun", "title": meta.get("title", ""),
                "publish_at": publish_at, "topic": meta.get("topic", ""),
                "quality_score": meta.get("quality_score")}
                
    import upload
    import boost
    import datetime as dt
    import re
    url = upload.upload(out, meta["title"], meta["description"], meta["hashtags"],
                        publish_at=publish_at, meta_tags=meta.get("tags"))
    log(f"Uploaded: {url}" + (f" (publishes {publish_at})" if publish_at else ""))
    
    video_id = url.rsplit("/", 1)[-1]
    try:
        import video_context
        video_context.save_context(video_id.split("=")[-1], meta)
    except Exception as e:
        log(f"video_context save skipped (non-fatal): {e}")
    
    try:
        cover = os.path.join(workdir, "cover.jpg")
        # For simplicity, if cover exists, use it.
        if os.path.exists(cover):
            upload.set_thumbnail(video_id, cover)
            log("Thumbnail applied to video")
    except Exception as e:
        log(f"Thumbnail step failed (non-fatal): {e}")
        
    src = "pool"
    n = boost.record_upload(video_id, meta["title"], meta.get("topic", ""), source=src, metadata=meta)
    
    try:
        ab_path = "ab_log.json"
        ab = {}
        if os.path.exists(ab_path):
            with open(ab_path) as f:
                ab = json.load(f)
        
        taxonomy = meta.get("taxonomy", "")
        subcluster = taxonomy.split("/")[1] if "/" in taxonomy else ""
        
        # merge (not replace) so analytics_poll metrics already on this id aren't clobbered.
        ab[video_id] = {**ab.get(video_id, {}),
            "variant": meta.get("variant", "A"),
            "title": meta.get("title", ""),
            "date": dt.date.today().isoformat(),
            "publish_at": publish_at,
            "cluster": meta.get("cluster"),
            "topic": meta.get("topic", ""),
            "subcluster": subcluster,
            "hook_type": meta.get("hook_type", ""),
            "series": meta.get("series", ""),
            "predicted_views_score": meta.get("predicted_views_score", 0.0),
            "retention_prediction": meta.get("retention_prediction", 0.0),
            "first_frame_score": meta.get("first_frame_score", 0.0),
            "viewer_identity_score": meta.get("viewer_identity_score", 0.0),
            "visual_thesis": meta.get("visual_thesis", ""),
            "first_frame_description": meta.get("first_frame_description", "")
        }
        with open(ab_path, "w") as f:
            json.dump(ab, f, indent=2)
    except Exception as e:
        log(f"ab_log write skipped in publish_draft: {e}")
    
    try:
        hook_text = ""
        script_text = meta.get("script", "")
        if script_text:
            first_sentence = script_text.replace("\n", ". ").split(". ")[0].strip()
            hook_text = first_sentence + ("." if not first_sentence.endswith((".", "?", "!")) else "")
        winner_memory.update_hook_library(
            title=meta.get("title", ""),
            hook_text=hook_text,
            hook_type=meta.get("hook_type", "explainer"),
            hook_structure=meta.get("hook_structure", ""),
            first_frame_description=meta.get("first_frame_description", ""),
            visual_thesis=meta.get("visual_thesis", "")
        )
    except Exception as e:
        log(f"Hook library update failed: {e}")

    try:
        import shutil as _sh
        _sh.rmtree(workdir, ignore_errors=True)
    except Exception as e:
        pass
        
    return {"url": url, "title": meta.get("title", ""),
            "publish_at": publish_at, "topic": meta.get("topic", ""),
            "quality_score": meta.get("quality_score")}


def ondemand_topic(text: str, cfg: dict, log=print) -> str:
    """Turn free-text into a rich topic for an everyday-frustrations video."""
    text = text.strip()
    return (f"ON-DEMAND video about {text}. Tell the single most relatable, surprising "
            f"explanation behind this universal human experience. Avoid academic design jargon. "
            f"Make it highly visual, relatable, and focus on the everyday annoyance or quirk of {text}.")


def _thumb_font() -> str:
    """Find a bold font file that exists on this OS (Windows drawtext needs an
    explicit fontfile; it can't auto-discover like Linux). Returns an ffmpeg-escaped
    path, or '' if none found (caller then renders without text rather than failing)."""
    import os as _os, platform as _pf
    candidates = []
    if _pf.system() == "Windows":
        candidates = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\Arialbd.ttf",
                      r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeuib.ttf",
                      r"C:\Windows\Fonts\impact.ttf"]
    elif _pf.system() == "Darwin":
        candidates = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                      "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    else:
        candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                      "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    for c in candidates:
        if _os.path.exists(c):
            # escape for ffmpeg filter: backslashes and the drive colon
            return c.replace("\\", "/").replace(":", "\\:")
    return ""


def _make_thumbnail(video_path: str, out_path: str, title: str, bg_photo: str = None):
    """Bold sports-channel thumbnail on the royalty-free footage: picks a dynamic
    frame, darkens with a cinematic gradient + vignette, then overlays a big
    left-aligned subject name, a gold hook word, and a colored accent bar.
    Falls back to a plain frame if drawtext fails."""
    import subprocess as _sp, re as _re, os as _os

    subject = (title.split(":")[0].strip() if ":" in title else title.strip())
    subject = _re.sub(r"\s*#.*$", "", subject)  # strip any trailing hashtags
    after = title.split(":", 1)[1] if ":" in title else ""
    after = _re.sub(r"\s*#.*$", "", after)
    # hook word: an ALL-CAPS emphatic word, else a punchy keyword, else nothing
    hookword = ""
    # 1) a vivid 1-2 word curiosity phrase
    PHRASES = ["MAKES YOU", "BUILT TO", "HIDDEN REASON", "DESIGN FLAW",
               "SECRET TRICK", "WHY THEY DO IT", "CHANGES EVERYTHING", "MIND CONTROL",
               "THE DARK TRUTH", "YOU NEVER KNEW", "MANIPULATION"]
    for ph in PHRASES:
        if ph.lower() in after.lower():
            hookword = ph; break
    # 2) one strong emphatic word
    if not hookword:
        PUNCH = ["TRICK", "WHY", "HIDDEN", "DESIGN", "CONTROL", "SECRET",
                 "FAKE", "SCAM", "GENIUS", "BANNED", "ILLEGAL"]
        hookword = next((p for p in PUNCH if p.lower() in after.lower()), "")
    # cap length so it fits one line; if nothing good, leave blank (no confusing fragment)
    if len(hookword) > 16:
        hookword = ""

    subject_up = subject[:26].upper()
    # Wrap long subjects to two lines so they never overflow. Prefer breaking at " VS ".
    def _wrap(s):
        if len(s) <= 13:
            return [s]
        if " VS " in s:
            a, b = s.split(" VS ", 1)
            return [a + " VS", b]
        words = s.split()
        if len(words) >= 2:
            mid = len(words) // 2
            return [" ".join(words[:mid]), " ".join(words[mid:])]
        return [s]
    subj_lines = _wrap(subject_up)
    # size so the LONGEST line fits within ~960px (≈ chars * size * 0.52)
    longest = max(len(l) for l in subj_lines)
    _subj_size = 96
    while _subj_size > 46 and longest * _subj_size * 0.52 > 960:
        _subj_size -= 4

    # choose the most "dynamic" frame: sample a few, keep the one with most motion/detail
    # (cheap proxy: pick the frame at 35% through, usually mid-action, not the intro card)
    raw = out_path + ".raw.jpg"
    if bg_photo and _os.path.exists(bg_photo):
        # use the dramatic stock football PHOTO as the background
        _os.replace(bg_photo, raw) if False else None
        import shutil as _sh; _sh.copy(bg_photo, raw)
    else:
        # fall back to a frame from the video itself
        _sp.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.2", "-i", video_path,
                 "-frames:v", "1", "-q:v", "2", raw], check=True, timeout=60)

    def esc(t):
        return t.replace("\\", "").replace(":", "\\:").replace("'", "").replace("%", "")

    _ff = _thumb_font()
    fontclause = f"fontfile='{_ff}':" if _ff else ""

    # cinematic stack: darken bottom third + left edge for text, vignette, accent bar, text
    vf = [
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "eq=contrast=1.12:saturation=1.25:brightness=-0.02",      # punchy grade
        "vignette=PI/4",                                           # cinematic edges
        "drawbox=x=0:y=ih-640:w=iw:h=640:color=black@0.66:t=fill", # bottom darken for text
        "drawbox=x=0:y=ih-640:w=18:h=640:color=#FFD24A@1.0:t=fill",# gold accent bar
        "drawbox=x=0:y=0:w=iw:h=130:color=black@0.4:t=fill",       # top scrim for brand tag
    ]
    vf.append(f"drawtext={fontclause}text='Hidden Logic':fontcolor=#FFD24A:fontsize=52:borderw=3:"
              "bordercolor=black:x=60:y=44")
    # subject name: big, bold, left-aligned above the bar area
    line_h = _subj_size + 14
    n = len(subj_lines)
    # stack subject lines; keep the gold hook word below them
    base_y = 380 + (n - 1) * line_h
    for i, ln in enumerate(subj_lines):
        vf.append(
            f"drawtext={fontclause}text='{esc(ln)}':fontcolor=white:fontsize={_subj_size}:"
            f"borderw=6:bordercolor=black@0.9:x=60:y=h-{base_y - i * line_h}")
    if hookword:
        hook_size = 120 if len(hookword) <= 8 else 92
        vf.append(
            f"drawtext={fontclause}text='{esc(hookword)}':fontcolor=#FFD24A:fontsize={hook_size}:"
            f"borderw=7:bordercolor=black@0.9:x=60:y=h-210")
    try:
        _sp.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-vf", ",".join(vf),
                 "-frames:v", "1", "-q:v", "2", out_path], check=True, timeout=60)
    except Exception:
        _os.replace(raw, out_path)
        return
    if _os.path.exists(raw):
        _os.remove(raw)


def _send_digest(cfg: dict, ok: int, fail: int, made: list, replies_posted: int = 0):
    """Build and send the end-of-run digest (schedule + viral + comments + attention).
    Used by BOTH the daily run and the on-demand path. Never raises."""
    try:
        import alerts
        had_failure = fail > 0 or ok == 0   # REAL problems only
        force_send = False                  # good news worth pinging even on a clean run

        # 1) what was made, WHEN it publishes, and the LINK to each (so you can click through)
        lines = []
        for r in made:
            title = (r.get("title", "") or "").split("#")[0].strip()
            when = "now"
            pa = r.get("publish_at")
            if pa:
                try:
                    _pub_utc = dt.datetime.fromisoformat(pa.replace("Z", "+00:00"))
                    # Show Singapore time explicitly. .astimezone() on the cloud runner returned
                    # UTC with no label, so "Sun 04:23 AM" was actually 12:23 PM SGT - correct
                    # but unreadable. Digest is for a human in Singapore; print SGT.
                    _pub_sgt = _pub_utc.astimezone(dt.timezone(dt.timedelta(hours=8)))
                    when = _pub_sgt.strftime("%a %I:%M %p") + " SGT"
                except Exception:
                    when = pa
            tag = " [preview]" if r.get("preview") else ""
            url = r.get("url", "")
            link = f"\n      {url}" if url and "dryrun" not in url else ""
            lines.append(f"  - {title}{tag}  ->  {when}{link}")
        schedule_block = "\n".join(lines) if lines else "  (no videos produced)"

        # 2) viral / fast-growth check (velocity vs the channel's norm)
        viral_block = ""
        try:
            fired = alerts.check_viral(cfg, log)
            if fired:
                vl = [f"  - {t} : {v:,} views (+{r}/hr)" for t, v, r in fired[:5]]
                viral_block = "\n\nGROWING FAST:\n" + "\n".join(vl)
                force_send = True   # good news - send it, but this is NOT a failure
        except Exception:
            pass

        # 3) new comments to attend to (count, not spammy per-comment)
        comments_block = ""
        try:
            ncom = alerts.check_new_comments(cfg, log)
            if ncom > 0:
                comments_block = f"\n\nNEW COMMENTS: {ncom} since last run."
                force_send = True   # good news - worth a ping
        except Exception:
            pass
        if replies_posted > 0:
            comments_block += (f"\n\nAUTO-REPLIES: posted {replies_posted} "
                               f"repl{'y' if replies_posted == 1 else 'ies'} to viewers.")

        # 4) things that need your attention (quota stress, quality misses, dropped slots)
        attn = list(ATTENTION)
        try:
            ev = scriptgen.RUN_EVENTS
            if ev.get("used_claude_fallback"):
                attn.append("Gemini ran out mid-run - used the Claude Code fallback "
                            "(fine, but your Gemini quota is getting tight).")
            elif ev.get("all_gemini_down", 0) >= 1:
                attn.append("Gemini hit limits during the run and recovered on other "
                            "models - quota is getting tight.")
            gf = ev.get("gate_fallbacks", 0)
            if gf >= 2:
                attn.append(f"{gf} videos published below the quality target (couldn't "
                            f"hit the score after retries) - worth a look at recent topics.")
        except Exception:
            pass
        attention_block = ""
        if attn:
            attention_block = "\n\nNEEDS ATTENTION:\n" + "\n".join(f"  - {a}" for a in attn)
            had_failure = True

        if had_failure:
            status = "needs attention"
        elif force_send:
            status = "all good (+ updates)"
        else:
            status = "all good"
        subject = f"Hidden Logic: {ok} made, {fail} failed - {status}"
        body = (f"Hidden Logic run finished.\n\n"
                f"Made {ok} video(s), {fail} failed.\n\n"
                f"PUBLISHING SCHEDULE:\n{schedule_block}"
                f"{viral_block}{comments_block}{attention_block}")
        # force-send on real failures OR good news (viral / comments), so neither is missed,
        # but the subject above stays honest about which it is.
        alerts.notify(cfg, subject, body, is_failure=(had_failure or force_send))
    except Exception as _e:
        log(f"alert send failed (non-fatal): {_e}")


def run_upload_only(cfg: dict, args, log):
    """Scan drafts/ recursively, upload completed drafts, and exit."""
    import upload
    import boost
    import winner_memory
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    db_lock = threading.Lock()

    # Check OAuth token first (triggers authentication browser if not set or invalid)
    if not args.dry_run:
        log("Validating/refreshing YouTube OAuth credentials...")
        try:
            upload._service()
            log("OAuth token is active and valid.")
        except Exception as e:
            log(f"OAuth validation failed: {e}")
            log("Please make sure yt_token.pickle exists or run in interactive terminal to authorize.")
            sys.exit(1)

    log("Scanning drafts/ directory recursively...")
    all_drafts = []
    already_uploaded_count = 0

    if not os.path.exists("drafts"):
        log("No drafts/ directory found!")
        sys.exit(0)

    for root, dirs, files in os.walk("drafts"):
        for file in files:
            if file == "short.mp4":
                video_path = os.path.join(root, file)
                workdir = root
                
                # Check for upload marker
                marker_path = os.path.join(workdir, "uploaded.txt")
                already = False
                if os.path.exists(marker_path) or os.path.exists(os.path.join(workdir, ".uploaded")):
                    already = True
                else:
                    meta_path = os.path.join(workdir, "meta.json")
                    if os.path.exists(meta_path):
                        try:
                            with open(meta_path, encoding="utf-8") as f:
                                meta = json.load(f)
                                if meta.get("uploaded") is True or "uploaded_url" in meta:
                                    already = True
                        except Exception:
                            pass
                
                if already:
                    already_uploaded_count += 1
                    continue

                # Load metadata
                meta = {}
                meta_path = os.path.join(workdir, "meta.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception as e:
                        log(f"Warning: Could not read metadata in {workdir}: {e}")
                
                all_drafts.append({
                    "video_path": video_path,
                    "workdir": workdir,
                    "meta": meta,
                    "score": float(meta.get("predicted_views_score", 0))
                })

    total_drafts_found = len(all_drafts) + already_uploaded_count
    log(f"Scan complete. Found {total_drafts_found} drafts total.")
    log(f"  - {already_uploaded_count} are already uploaded (skipped)")
    log(f"  - {len(all_drafts)} are pending upload")

    if not all_drafts:
        log("No pending drafts to upload.")
        print_upload_summary(total_drafts_found, 0, 0, already_uploaded_count)
        sys.exit(0)

    # Sort drafts by predicted_views_score descending to publish best first
    all_drafts.sort(key=lambda x: x["score"], reverse=True)

    # Assign scheduling slots if not --immediate
    publish_at_slots = []
    if not args.immediate:
        log("Computing scheduling slots...")
        slot_times = compute_publish_slots(cfg, len(all_drafts) - 1)
        for i in range(len(all_drafts)):
            if i == 0:
                publish_at_slots.append(None) # First video published public immediately
            else:
                if i - 1 < len(slot_times):
                    publish_at_slots.append(_to_utc_iso(slot_times[i - 1]))
                else:
                    last_slot = slot_times[-1] if slot_times else dt.datetime.now()
                    extra_delay = dt.timedelta(hours=(i - len(slot_times)) * 2)
                    publish_at_slots.append(_to_utc_iso(last_slot + extra_delay))
    else:
        log("Uploading all videos as public immediately (no scheduling slots).")
        publish_at_slots = [None] * len(all_drafts)

    def upload_single_draft(video_path: str, workdir: str, meta: dict, publish_at: str | None) -> str:
        title = meta.get("title", "Untitled Short")
        description = meta.get("description", "")
        hashtags = meta.get("hashtags", [])
        tags = meta.get("tags", [])
        topic = meta.get("topic", "")

        if args.dry_run:
            log(f"[DRY-RUN] Would upload {video_path} | Title: {title} | Publish At: {publish_at}")
            return "https://youtube.com/watch?v=dryrun"

        log(f"Starting upload for {video_path}...")
        url = upload.upload(video_path, title, description, hashtags, publish_at=publish_at, meta_tags=tags)
        log(f"Uploaded: {url}" + (f" (publishes {publish_at})" if publish_at else ""))
        try:
            import video_context
            video_context.save_context(url.rsplit("/", 1)[-1].split("=")[-1], meta)
        except Exception as e:
            log(f"video_context save skipped (non-fatal): {e}")
        
        video_id = url.rsplit("/", 1)[-1]

        # Apply Thumbnail if cover.jpg exists
        try:
            cover = os.path.join(workdir, "cover.jpg")
            if os.path.exists(cover):
                upload.set_thumbnail(video_id, cover)
                log(f"Thumbnail applied for {video_id}")
        except Exception as e:
            log(f"Thumbnail application failed (non-fatal) for {video_id}: {e}")

        # Record Upload in channel index
        src = "pool"
        with db_lock:
            try:
                n = boost.record_upload(video_id, title, topic, source=src, metadata=meta)
                log(f"Recorded upload #{n} in channel index")
            except Exception as e:
                log(f"Failed to record upload in channel index: {e}")

        # Localization
        try:
            boost.localize(video_id, title, description)
            log(f"Localized {video_id} to ES/PT")
        except Exception as e:
            log(f"Localization failed (non-fatal) for {video_id}: {e}")

        # Self-like (queued for scheduled videos - a like on a still-private video is unreliable)
        try:
            if publish_at:
                _queue_pending_comment(video_id, "", publish_at, kind="like")
                log(f"Queued self-like for {video_id} (posts when live)")
            else:
                upload.post_like(video_id)
                log(f"Self-liked {video_id}")
        except Exception as e:
            log(f"Self-like failed (non-fatal) for {video_id}: {e}")

        # First comment
        if meta.get("first_comment"):
            if not publish_at:
                try:
                    upload.post_comment(video_id, meta["first_comment"])
                    log(f"Seeded first comment for {video_id}: {meta['first_comment']}")
                except Exception as e:
                    log(f"First comment failed (non-fatal) for {video_id}: {e}")
            else:
                try:
                    _queue_pending_comment(video_id, meta["first_comment"], publish_at)
                    log(f"Queued first comment for {video_id} (posts when live)")
                except Exception as e:
                    log(f"Could not queue pending comment for {video_id} (non-fatal): {e}")

        # Update Hook Library
        try:
            hook_text = ""
            script_text = meta.get("script", "")
            if script_text:
                first_sentence = script_text.replace("\n", ". ").split(". ")[0].strip()
                hook_text = first_sentence + ("." if not first_sentence.endswith((".", "?", "!")) else "")
            
            with db_lock:
                winner_memory.update_hook_library(
                    title=title,
                    hook_text=hook_text,
                    hook_type=meta.get("hook_type", "explainer"),
                    hook_structure=meta.get("hook_structure", ""),
                    first_frame_description=meta.get("first_frame_description", ""),
                    visual_thesis=meta.get("visual_thesis", "")
                )
                log(f"Updated hook library for {video_id}")
        except Exception as e:
            log(f"Hook library update failed (non-fatal) for {video_id}: {e}")

        # Update A/B test log
        try:
            with db_lock:
                ab_path = "ab_log.json"
                ab = {}
                if os.path.exists(ab_path):
                    with open(ab_path) as f:
                        ab = json.load(f)
                taxonomy = meta.get("taxonomy", "")
                subcluster = taxonomy.split("/")[1] if "/" in taxonomy else ""
                ab[video_id] = {
                    "variant": meta.get("variant", "A"),
                    "title": title,
                    "date": dt.date.today().isoformat(),
                    "publish_at": publish_at,
                    "cluster": meta.get("cluster"),
                    "topic": topic,
                    "subcluster": subcluster,
                    "hook_type": meta.get("hook_type", ""),
            "series": meta.get("series", ""),
                    "predicted_views_score": meta.get("predicted_views_score", 0.0),
                    "retention_prediction": meta.get("retention_prediction", 0.0),
                    "first_frame_score": meta.get("first_frame_score", 0.0),
                    "viewer_identity_score": meta.get("viewer_identity_score", 0.0),
                    "visual_thesis": meta.get("visual_thesis", ""),
                    "first_frame_description": meta.get("first_frame_description", "")
                }
                with open(ab_path, "w") as f:
                    json.dump(ab, f, indent=2)
                log(f"Recorded variant data in ab_log.json for {video_id}")
        except Exception as e:
            log(f"ab_log write skipped (non-fatal) for {video_id}: {e}")

        # Write markers
        timestamp = dt.datetime.now().isoformat()
        try:
            with open(os.path.join(workdir, "uploaded.txt"), "w", encoding="utf-8") as f:
                f.write(f"Uploaded URL: {url}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Publish At: {publish_at}\n")
        except Exception as e:
            log(f"Failed to write marker file in {workdir}: {e}")

        meta_path = os.path.join(workdir, "meta.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    m = json.load(f)
                m["uploaded"] = True
                m["uploaded_url"] = url
                m["uploaded_at"] = timestamp
                if publish_at:
                    m["publish_at"] = publish_at
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(m, f, indent=2)
            except Exception as e:
                log(f"Failed to update meta.json in {workdir}: {e}")

        return url

    # Process uploads in parallel
    succeeded_count = 0
    failed_count = 0
    futures = {}

    log(f"Starting parallel upload queue using {args.max_workers} worker threads...")
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        for idx, draft in enumerate(all_drafts):
            publish_at = publish_at_slots[idx]
            future = executor.submit(
                upload_single_draft, 
                draft["video_path"], 
                draft["workdir"], 
                draft["meta"], 
                publish_at
            )
            futures[future] = draft["workdir"]

        for future in as_completed(futures):
            workdir = futures[future]
            try:
                url = future.result()
                succeeded_count += 1
                log(f"SUCCESS: {workdir} uploaded successfully -> {url}")
            except Exception as e:
                failed_count += 1
                log(f"FAILED: {workdir} upload failed:")
                log(traceback.format_exc())

    print_upload_summary(total_drafts_found, succeeded_count, failed_count, already_uploaded_count)

def print_upload_summary(total, succeeded, failed, already):
    print("\n" + "="*40)
    print("           UPLOAD RUN SUMMARY")
    print("="*40)
    print(f"* Total drafts found: {total}")
    print(f"* Successfully uploaded: {succeeded}")
    print(f"* Failed uploads: {failed}")
    print(f"* Already uploaded: {already}")
    print("="*40 + "\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--compile-now", action="store_true",
                        help="build and upload the weekly compilation immediately")
    parser.add_argument("--topic", type=str, default=None,
                        help='on-demand: make ONE video about this subject and publish now. '
                             'e.g. --topic "Brazil vs Morocco" or --topic "Vinicius Jr"')

    parser.add_argument("--strict-topic-lock", action="store_true", default=None,
                        help="force strict topic-lock mode (do not swap/broaden the subject)")
    parser.add_argument("--no-strict-topic-lock", action="store_true", default=None,
                        help="disable strict topic-lock mode (allow viral broadening)")
    parser.add_argument("--upload-only", action="store_true",
                        help="scan drafts/ recursively, upload completed drafts, and exit")
    parser.add_argument("--immediate", action="store_true",
                        help="for --upload-only: upload all drafts as public immediately without scheduling slots")
    parser.add_argument("--max-workers", type=int, default=3,
                        help="for --upload-only: maximum parallel uploads (default: 3)")
    parser.add_argument("--hero", action="store_true",
                        help="auto-pick today's single best topic (via morning_brief) as video #1 "
                             "of the normal daily quota - the full-autopilot mode, no human input")
    args = parser.parse_args()

    # startup integrity check: catches mismatched file swaps with a clear message
    import inspect
    problems = []
    if "music_volume" not in inspect.signature(assemble.assemble).parameters:
        problems.append("assemble.py")
    for mod, attr in ((scriptgen, "generate"), (tts, "synthesize"), (boost, "is_duplicate_title"),
                      (boost, "sync_channel_index")):
        if not hasattr(mod, attr):
            problems.append(mod.__name__ + ".py")
    if problems:
        sys.exit("FILES OUT OF SYNC: " + ", ".join(sorted(set(problems))) +
                 " do not match this run_daily.py. Update all files from the same version together.")

    import config_loader
    cfg = config_loader.load_config(CONFIG_FILE)
    # one-time security nudge if live secrets are still sitting in config.json
    try:
        _leaked = config_loader.warn_if_secrets_in_file(CONFIG_FILE)
        if _leaked:
            flag("Secrets are stored in config.json in plaintext - move to HL_* env vars and rotate if the folder was ever shared.")
    except Exception:
        pass

    if args.upload_only:
        run_upload_only(cfg, args, log)
        return

    if not args.dry_run:
        try:
            boost.sync_channel_index(log)
        except Exception as e:
            log(f"index sync failed (non-fatal): {e}")
        try:
            winner_memory.update_memory(cfg, log)
        except Exception as e:
            log(f"winner_memory update failed (non-fatal): {e}")
        # Pull fresh retention/AVD from YouTube Analytics for recently published videos BEFORE
        # we pick topics, so the retention feedback loop (stay-to-watch per cluster) is current.
        # Without this, avg_stayed_to_watch stays None and the system ranks clusters on raw
        # views only. Non-fatal: a poll failure (e.g. API hiccup) never blocks the run.
        try:
            import analytics_poll
            log("Polling YouTube Analytics for fresh retention data...")
            analytics_poll.main()
            # re-load winner_memory so the just-polled retention is reflected in this run's picks
            try:
                winner_memory.update_memory(cfg, log)
            except Exception:
                pass
        except Exception as e:
            log(f"analytics poll failed (non-fatal, using existing data): {e}")

        # Post any first-comments that were queued for scheduled videos which are now live.
        try:
            _flush_pending_comments(log)
        except Exception as e:
            log(f"pending-comment flush failed (non-fatal): {e}")
        try:
            analyzer.analyze(cfg, log)  # learn from yesterday before producing today
        except Exception as e:
            log(f"analyzer failed (non-fatal): {e}")

    # Resolve strict_topic_lock. Precedence:
    #   1. explicit CLI flags always win
    #   2. an explicit --topic is a deliberate human choice -> LOCK by default, even if
    #      config.json sets strict_topic_lock=false (that setting is for DAILY auto-generation,
    #      where the reviewer is allowed to refine a machine-picked seed; a topic YOU typed
    #      should not be silently swapped for a different subject).
    #   3. otherwise fall back to the config value (default False for daily runs).
    strict_topic_lock = cfg.get("strict_topic_lock", False)
    if args.strict_topic_lock:
        strict_topic_lock = True
    elif args.no_strict_topic_lock:
        strict_topic_lock = False
    elif args.topic:
        strict_topic_lock = True

    if args.topic:
        log(f"ON-DEMAND: generating one video for '{args.topic}'")
        topic = ondemand_topic(args.topic, cfg, log)
        import time
        workdir = os.path.join("output", f"{dt.datetime.now().strftime('%Y%m%d')}_ondemand_{int(time.time())}")
        rec, failed = None, 0
        try:
            rec = make_one(cfg, workdir, args.dry_run, None, topic=topic, strict_topic_lock=strict_topic_lock)
            log("ON-DEMAND: done.")
        except Exception as e:
            failed = 1
            log(f"ON-DEMAND failed: {e}")
            log(traceback.format_exc())
        if not args.dry_run:
            made = [rec] if isinstance(rec, dict) else []
            replies_posted = 0
            try:
                import post_replies
                replies_posted = post_replies.run_auto_replies(cfg, log)
            except Exception as e:
                log(f"auto-replies failed (non-fatal): {e}")
            _send_digest(cfg, ok=(1 - failed), fail=failed, made=made,
                         replies_posted=replies_posted)
        return

    n = args.count or cfg.get("videos_per_day", 2)
    overrides = []

    # IDEA BANK: pull a couple of validated Reddit-mined topics per run (proven engagement,
    # not the pool's guesses). Config 'bank_videos_per_day' sets how many slots the bank fills
    # (default 2); the REST of the day's slots are left for live trends + the smart pool, so
    # each day mixes proven-evergreen ideas with timely ones. When the bank runs low it warns
    # you in the log. Non-fatal: if the bank is empty/missing, the pool fills everything.
    bank_n = cfg.get("bank_videos_per_day", 2)
    # never let the bank take ALL slots - always leave at least 1 for trend/pool when n>1
    if n > 1:
        bank_n = min(bank_n, n - 1)
    if not args.topic and bank_n > 0:  # don't override an explicit single-topic run
        try:
            import idea_bank
            bank_titles = idea_bank.pick_unused(bank_n, log=log)
            if bank_titles:
                overrides = list(bank_titles)
                log(f"Idea bank: filling {len(overrides)} of {n} slots with validated topics: "
                    + "; ".join(overrides))
        except Exception as e:
            log(f"idea bank pick failed (non-fatal, pool fills in): {e}")

    # FULL AUTOPILOT (--hero): the pool's own LLM topic-filter already makes excellent
    # evergreen picks, so we DON'T override it for ordinary topics. We only override a slot
    # when something is genuinely LIVE right now (a World Cup match, a race weekend) - the one
    # thing the pool can't know about. The trend hero takes the NEXT open slot after the bank.
    # Non-fatal: any failure just means the pool picks remaining videos.
    if args.hero:
        try:
            import morning_brief
            hero = morning_brief.pick_trend_hero()
            if hero and hero not in overrides:
                # put the live-trend topic right after the bank picks (timely + proven mix)
                if len(overrides) < n:
                    overrides.append(hero)
                    log(f"AUTOPILOT: live trend detected - added as slot #{len(overrides)} of {n}: {hero}")
            elif not hero:
                log(f"AUTOPILOT: no live trend today - bank + smart pool fill all {n} videos.")
        except Exception as e:
            log(f"AUTOPILOT hero check failed (non-fatal), pool picks rest: {e}")
    
    # All videos are generated from the trend-weighted pool for 'Everyday Mysteries Explained'
    log(f"Daily mix: {n} pool video(s)")

    spread = float(cfg.get("spread_hours", 0))
    # If video #1 posts immediately, we only need n-1 scheduled slots (for videos #2..n).
    # Requesting n would compute an extra slot that rolls to the next day. When NOT posting
    # #1 now (off-peak hold), we need all n slots.
    _slots_needed = (n - 1) if cfg.get("post_first_immediately", True) else n
    slot_times = compute_publish_slots(cfg, max(_slots_needed, 1))
    if slot_times:
        log("Publish slots: now, then " + ", ".join(t.strftime("%a %H:%M") for t in slot_times))
    stamp = dt.datetime.now().strftime("%Y%m%d")
    ok, fail = 0, 0
    made = []  # digest records for the end-of-run summary alert
    _drop_reasons = {"hook_not_physical": 0, "first_frame_low": 0, "topic_recognition_low": 0, "retention_pred_low": 0, "viewer_identity_low": 0, "title_score_low": 0, "quality_floor": 0, "winner_clone": 0, "subcluster_clone": 0, "other": 0}
    
    # 1. Generate Drafts
    drafts_dir = "drafts"
    os.makedirs(drafts_dir, exist_ok=True)
    
    # Buffer size: generate more drafts than needed, then publish the best N (quality
    # competition). Default multiplier is 2x, but on slow days (Gemini quota-limited -> Claude
    # Buffer size: normally generate more drafts than needed, then publish the best N (quality
    # competition). BUT when the idea bank + trend already supply enough locked, pre-validated
    # topics to cover all N slots, extra buffer drafts add nothing - they'd be drawn from the
    # free pool, which (with most clusters on cooldown) just grinds out near-duplicate repeats.
    # So: if overrides already cover N, make exactly N (all locked, no pool free-wheeling -> far
    # faster and no repeats). Only over-generate when the pool is actually filling slots.
    mult = cfg.get("draft_buffer_multiplier", 2.0)
    if len(overrides) >= n:
        drafts_to_make = n  # fully covered by bank+trend; no extra pool drafts needed
        log(f"Phase 1: Generating {drafts_to_make} drafts (all locked from bank/trend, no pool extras)...")
    else:
        drafts_to_make = max(int(round(n * mult)), n + 1, 5) if not args.dry_run else n
        pool_slots = drafts_to_make - len(overrides)
        log(f"Phase 1: Generating {drafts_to_make} drafts for the buffer "
            f"({len(overrides)} locked + {pool_slots} pool, best {n} will publish)...")
    for slot_idx in range(drafts_to_make):
        workdir = os.path.join(drafts_dir, f"draft_{stamp}_{slot_idx+1}")
        if os.path.exists(workdir) and os.path.exists(os.path.join(workdir, "short.mp4")):
            continue
            
        try:
            slot_topic = overrides[slot_idx] if slot_idx < len(overrides) else None
            # A trend-hero override is a deliberate, time-sensitive pick: lock it so it can't
            # drift to a different subject. Pool topics (no override) stay flexible so the
            # selector keeps its variety.
            slot_lock = True if slot_topic is not None else strict_topic_lock
            make_one(cfg, workdir, args.dry_run, None,
                           topic=slot_topic,
                           strict_topic_lock=slot_lock, generate_only=True)
        except Exception as e:
            log(f"ERROR generating draft {slot_idx + 1}: {e}")
            err_str = str(e)
            if "[hook_not_physical]" in err_str: _drop_reasons["hook_not_physical"] = _drop_reasons.get("hook_not_physical", 0) + 1
            elif "[first_frame_low]" in err_str: _drop_reasons["first_frame_low"] = _drop_reasons.get("first_frame_low", 0) + 1
            elif "[topic_recognition_low]" in err_str: _drop_reasons["topic_recognition_low"] = _drop_reasons.get("topic_recognition_low", 0) + 1
            elif "[retention_pred_low]" in err_str: _drop_reasons["retention_pred_low"] = _drop_reasons.get("retention_pred_low", 0) + 1
            elif "[viewer_identity_low]" in err_str: _drop_reasons["viewer_identity_low"] = _drop_reasons.get("viewer_identity_low", 0) + 1
            elif "[title_score_low]" in err_str: _drop_reasons["title_score_low"] = _drop_reasons.get("title_score_low", 0) + 1
            elif "[quality_floor]" in err_str: _drop_reasons["quality_floor"] = _drop_reasons.get("quality_floor", 0) + 1
            elif "[winner_clone]" in err_str: _drop_reasons["winner_clone"] = _drop_reasons.get("winner_clone", 0) + 1
            elif "[subcluster_clone]" in err_str: _drop_reasons["subcluster_clone"] = _drop_reasons.get("subcluster_clone", 0) + 1
            else: _drop_reasons["other"] = _drop_reasons.get("other", 0) + 1

    # 2. Rank and Publish Drafts (80/20 Exploration)
    log("Phase 2: Ranking drafts and publishing...")
    available_drafts = []
    for d in os.listdir(drafts_dir):
        meta_path = os.path.join(drafts_dir, d, "meta.json")
        if os.path.exists(meta_path) and os.path.exists(os.path.join(drafts_dir, d, "short.mp4")):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                # Skip already uploaded drafts
                if meta.get("uploaded") is True or os.path.exists(os.path.join(drafts_dir, d, "uploaded.txt")):
                    continue
                available_drafts.append({
                    "dir": os.path.join(drafts_dir, d),
                    "score": float(meta.get("predicted_views_score", 0)),
                    "taxonomy": meta.get("taxonomy", ""),
                    "meta": meta
                })
            except Exception:
                pass
                
    # Sort by score descending
    available_drafts.sort(key=lambda x: x["score"], reverse=True)
    
    if not available_drafts:
        log("No valid drafts available to publish!")
    else:
        # Adaptive Exploration Queue Allocation
        cluster_data_count = 0
        if os.path.exists("channel_index.json"):
            try:
                with open("channel_index.json", encoding="utf-8") as f:
                    cluster_data_count = len(json.load(f))
            except Exception: pass
            
        exploration_rate = 0.30 if cluster_data_count < 10 else 0.15
        explore_count = int(round(n * exploration_rate))
        exploit_count = n - explore_count
        
        # Track under-tested clusters for exploration
        cluster_strengths = winner_memory.get_cluster_strengths()
        under_tested_clusters = {c for c, strength in cluster_strengths.items() if strength <= 3.0}
        
        to_publish = []
        # Select Exploit drafts (highest scores)
        for d in available_drafts:
            if len(to_publish) >= exploit_count:
                break
            to_publish.append(d)
            
        # Select Explore drafts (under-tested or completely novel)
        for d in available_drafts:
            if len(to_publish) >= n:
                break
            if d not in to_publish:
                cluster = d["taxonomy"].split("/")[0] if "/" in d["taxonomy"] else ""
                if cluster in under_tested_clusters or cluster not in cluster_strengths:
                    to_publish.append(d)
                    
        # Fill any remaining slots with highest scores if exploration didn't find matches
        for d in available_drafts:
            if len(to_publish) >= n:
                break
            if d not in to_publish:
                to_publish.append(d)
                
        # Video #1 publishing policy. By default (post_first_immediately=True) video #1 ALWAYS
        # goes out now and the rest schedule to the configured slots - this is what the channel
        # wants: one instant post per run, no waiting. The old peak-window behavior (hold #1 for
        # the next peak slot when running at a dead hour) is still available by setting
        # post_first_immediately=False in config, for anyone who'd rather never post off-peak.
        _now_local = dt.datetime.now()
        _post_first_now = cfg.get("post_first_immediately", True)
        # post_first_immediately=False now means EXACTLY that: never post any video immediately -
        # every video goes to a configured slot. (The old "peak window" heuristic used the
        # runner's LOCAL clock; on the UTC cloud runner, its 14:00-23:00 "peak" = 10pm-7am
        # Singapore, so video #1 kept posting in the middle of the night. Heuristic removed.)
        _in_peak = bool(_post_first_now)
        if not _post_first_now:
            log("post_first_immediately=False - scheduling ALL videos to configured slots.")
        else:
            log(f"Posting video #1 now; videos #2-{n} scheduled to slots.")
        for slot_idx, draft in enumerate(to_publish):
            publish_at = None
            if _in_peak:
                # #1 now, the rest at the configured slots
                if slot_idx > 0:
                    if slot_times:
                        publish_at = _to_utc_iso(slot_times[min(slot_idx - 1, len(slot_times) - 1)])
                    elif spread > 0 and n > 1:
                        delay = dt.timedelta(hours=spread * slot_idx / max(1, n - 1))
                        publish_at = (dt.datetime.now(dt.timezone.utc) + delay).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                # off-peak with post_first_immediately=False: schedule EVERY video to peak slots
                if slot_times:
                    publish_at = _to_utc_iso(slot_times[min(slot_idx, len(slot_times) - 1)])
                elif spread > 0 and n > 1:
                    delay = dt.timedelta(hours=2 + spread * slot_idx / max(1, n - 1))
                    publish_at = (dt.datetime.now(dt.timezone.utc) + delay).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            try:
                rec = publish_draft(cfg, draft["dir"], args.dry_run, publish_at)
                if isinstance(rec, dict):
                    made.append(rec)
                ok += 1
            except Exception as e:
                _emsg = str(e)
                # Quota / daily upload limit: stop the batch and KEEP the remaining drafts for the
                # next run instead of burning fail counts and losing them. Surfaced in the digest.
                if "quota" in _emsg.lower() or "uploadlimitexceeded" in _emsg.lower() or type(e).__name__ == "UploadQuotaError":
                    _deferred = len(to_publish) - slot_idx
                    flag(f"YouTube upload quota reached - {_deferred} video(s) deferred to the next run.")
                    log(f"Upload quota/limit hit - stopping publish batch; {_deferred} draft(s) kept for next run.")
                    break
                fail += 1
                log(f"ERROR publishing draft {draft['dir']}: {_emsg}")
                flag(f"A video failed to publish: {_emsg[:140]}")

        # CLEAN UP BUFFER LOSERS: drafts generated to over-fill the buffer but NOT selected for
        # publishing are never reused. Left behind they leak ~140 MB each forever AND look like
        # valid pending uploads to --upload-only (risking duplicate uploads). Published drafts
        # already self-clean inside publish_draft; remove only the unselected, un-uploaded rest.
        if not args.dry_run:
            import shutil as _sh2
            _keep_dirs = {d.get("dir") for d in to_publish}
            for d in available_drafts:
                _ddir = d.get("dir")
                if _ddir and _ddir not in _keep_dirs and os.path.isdir(_ddir):
                    try:
                        _sh2.rmtree(_ddir, ignore_errors=True)
                        log(f"Cleaned unused buffer draft: {os.path.basename(_ddir)}")
                    except Exception as _ce:
                        log(f"Could not clean buffer draft {_ddir}: {_ce}")

    if not args.dry_run:
        try:
            boost.run_weekly_tasks(cfg, log)
        except Exception as e:
            log(f"weekly boost tasks failed (non-fatal): {e}")
        try:
            if args.compile_now or compilation.due_this_weekend():
                log("WEEKEND COMPILATION: building this week's best-of...")
                compilation.run_weekly_compilation(cfg, log)
        except Exception as e:
            log(f"weekly compilation failed (non-fatal): {e}")
    log(f"Done. {ok} succeeded, {fail} failed.")
    # Cumulative slot tracking
    try:
        stats_path = "slot_stats.json"
        s_stats = {"generated": 0, "published": 0, "dropped": 0, "total_quality": 0.0, "avg_quality": 0.0,
                   "drop_reasons": {"hook_not_physical": 0, "first_frame_low": 0, "topic_recognition_low": 0, "retention_pred_low": 0, "viewer_identity_low": 0, "title_score_low": 0, "quality_floor": 0, "other": 0}}
        if os.path.exists(stats_path):
            with open(stats_path) as sf:
                try:
                    loaded = json.load(sf)
                    for k in ("generated", "published", "dropped", "total_quality", "avg_quality"):
                        if k in loaded:
                            s_stats[k] = loaded[k]
                    # Restore total_quality from published and avg_quality
                    s_stats["total_quality"] = float(s_stats["published"] * s_stats["avg_quality"])
                    # Merge existing drop_reasons
                    if "drop_reasons" in loaded:
                        for rk, rv in loaded["drop_reasons"].items():
                            s_stats["drop_reasons"][rk] = s_stats["drop_reasons"].get(rk, 0) + rv
                except Exception:
                    pass
        
        s_stats["generated"] += ok + fail
        s_stats["published"] += ok
        s_stats["dropped"] += fail
        for rk, rv in _drop_reasons.items():
            s_stats["drop_reasons"][rk] = s_stats["drop_reasons"].get(rk, 0) + rv
        
        for r in made:
            if isinstance(r, dict) and r.get("quality_score") is not None:
                s_stats["total_quality"] += float(r["quality_score"])
                
        if s_stats["published"] > 0:
            s_stats["avg_quality"] = round(s_stats["total_quality"] / s_stats["published"], 1)
        else:
            s_stats["avg_quality"] = 0.0
            
        # Clean up total_quality field from final JSON to keep it clean and match requested schema exactly
        final_stats = {
            "generated": s_stats["generated"],
            "published": s_stats["published"],
            "dropped": s_stats["dropped"],
            "avg_quality": s_stats["avg_quality"],
            "drop_reasons": s_stats["drop_reasons"]
        }
        with open(stats_path, "w") as sf:
            json.dump(final_stats, sf, indent=2)
        log(f"[slots_tracker] Slot Stats: generated={final_stats['generated']}, published={final_stats['published']}, dropped={final_stats['dropped']}, avg_quality={final_stats['avg_quality']:.1f}")
        if any(v > 0 for v in final_stats['drop_reasons'].values()):
            log(f"[slots_tracker] Drop Reasons: {final_stats['drop_reasons']}")
    except Exception as se:
        log(f"[slots_tracker] Failed to update slot stats: {se}")
    # auto-reply to recent comments in the channel voice (full-auto, after videos)
    replies_posted = 0
    if not args.dry_run:
        try:
            import post_replies
            replies_posted = post_replies.run_auto_replies(cfg, log)
        except Exception as e:
            log(f"auto-replies failed (non-fatal): {e}")
    if not args.dry_run:
        _send_digest(cfg, ok=ok, fail=fail, made=made, replies_posted=replies_posted)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # a total crash on an unattended laptop must still reach you. Try to load
        # config just for the alert, then re-raise so the error is still logged.
        import traceback as _tb
        _err = _tb.format_exc()
        print(_err)
        try:
            import alerts as _alerts
            # Use config_loader so the alert still sends if secrets (incl. the webhook) were
            # moved to HL_* environment variables instead of config.json.
            try:
                import config_loader as _cl
                _cfg = _cl.load_config("config.json")
            except Exception:
                import json as _json
                with open("config.json", encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
            _alerts.notify(_cfg, "Hidden Logic CRASHED (whole run failed)",
                           "The daily run crashed before finishing:\n\n" + _err[-1500:],
                           is_failure=True)
        except Exception:
            pass
        raise
