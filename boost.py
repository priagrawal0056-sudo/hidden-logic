"""
boost.py - Growth engine: channel index, weekly revive pass, auto-sequels,
ES/PT localization, and comment-reply drafting.
All functions are non-fatal by design: a failure here never blocks publishing.
"""
import datetime as dt
import json
import os

import scriptgen
import upload

INDEX_FILE = "channel_index.json"
REVIVED_FILE = "revived.json"
SEQUELS_FILE = "sequels.json"
LAST_BOOST_FILE = "last_boost.json"
DRAFTS_FILE = "reply_drafts.txt"


def _load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------- channel index
def record_upload(video_id: str, title: str, topic: str, source: str = "pool", metadata: dict | None = None) -> int:
    """Track every upload; returns this video's series number."""
    idx = _load(INDEX_FILE, [])
    n = len(idx) + 1
    entry = {"video_id": video_id, "title": title, "topic": topic,
             "date": dt.date.today().isoformat(), "n": n, "source": source}
    if metadata:
        for k in ("relatability_score", "memory_trigger_score", "curiosity_score", 
                  "visual_score", "environment_bonus", "topic_fidelity", 
                  "subject_retention", "quality_score", "trend_heat", "variant", "hook_type"):
            if k in metadata:
                entry[k] = metadata[k]
    idx.append(entry)
    _save(INDEX_FILE, idx)
    return n


def next_series_number() -> int:
    return len(_load(INDEX_FILE, [])) + 1


# ---------------------------------------------------------------- auto-sequels
def pick_sequel_topic(cfg: dict) -> str | None:
    """If a past video crossed the view threshold and hasn't been sequel'd,
    return a Part 2 topic (marked used immediately: no duplicate sequels)."""
    threshold = int(cfg.get("sequel_threshold", 500))
    idx = _load(INDEX_FILE, [])
    done = set(_load(SEQUELS_FILE, []))
    candidates = [v for v in idx if v["video_id"] not in done]
    if not candidates:
        return None
    try:
        stats = upload.video_stats([v["video_id"] for v in candidates[-50:]])
    except Exception:
        return None
    # Pull per-video retention from ab_log.json (stayed_to_watch is the field actually written;
    # the old code read view_velocity.json, which never stores retention, so the multiplier was
    # always 1.0). Now we genuinely sequel the videos people FINISHED, not just high-impression ones.
    retention = {}
    try:
        import json as _j
        if os.path.exists("ab_log.json"):
            ab = _j.load(open("ab_log.json", encoding="utf-8"))
            for vid, info in ab.items():
                if not isinstance(info, dict):
                    continue
                r = info.get("stayed_to_watch")
                if r is None:
                    r = info.get("retention")
                if r is not None:
                    retention[vid] = float(r)
    except Exception:
        retention = {}

    best, best_rank, best_views = None, -1.0, 0
    for v in candidates[-50:]:
        vid = v["video_id"]
        views = int((stats.get(vid) or {}).get("viewCount", 0))
        if views < threshold:
            continue
        ret = retention.get(vid)
        # retention multiplier: 1.0 if unknown, up to ~1.8 for strongly-retained videos.
        mult = 1.0 + min(max((ret - 40.0) / 60.0, -0.3), 0.8) if ret is not None else 1.0
        rank = views * mult
        if rank > best_rank:
            best, best_rank, best_views = v, rank, views
    if not best:
        return None
    done.add(best["video_id"])
    _save(SEQUELS_FILE, sorted(done))
    return (f"PART 2 follow-up to a hit video titled '{best['title']}' "
            f"(original topic: {best['topic']}). Open with a callback hook like "
            f"'You loved the last one, but I kept the craziest fact back...' then "
            f"deliver new, even stronger material on the same subject. {best_views} "
            f"people watched part 1, so reward them.")


# ---------------------------------------------------------------- localization
def localize(video_id: str, title: str, description: str):
    """Add Spanish + Portuguese metadata so the Short surfaces for football's
    biggest audiences."""
    prompt = (f"Translate this YouTube Shorts title and description to Spanish and "
              f"Portuguese. Keep emojis, keep names unchanged, keep it punchy.\n"
              f"Title: {title}\nDescription: {description}\n"
              'Respond ONLY with JSON: {"es": {"title": "...", "description": "..."}, '
              '"pt": {"title": "...", "description": "..."}}')
    loc = scriptgen._call("", prompt, 0.3) if scriptgen.PROVIDER == "claude_code" else None
    if loc is None:
        import json as _j
        # gemini path needs the key from config
        cfg = _j.load(open("config.json"))
        loc = scriptgen._call(cfg.get("gemini_api_key", ""), prompt, 0.3)
    upload.set_localizations(video_id, {
        "es": {"title": loc["es"]["title"][:95], "description": loc["es"]["description"][:1000]},
        "pt": {"title": loc["pt"]["title"][:95], "description": loc["pt"]["description"][:1000]},
    })


# ---------------------------------------------------------------- revive pass
def revive(cfg: dict, log=print, max_videos: int = 3):
    """Weekly: re-title videos stuck under the view floor after 48h."""
    floor = int(cfg.get("revive_view_floor", 100))
    idx = _load(INDEX_FILE, [])
    revived = set(_load(REVIVED_FILE, []))
    cutoff = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    candidates = [v for v in idx if v["date"] <= cutoff and v["video_id"] not in revived]
    if not candidates:
        return
    try:
        stats = upload.video_stats([v["video_id"] for v in candidates[-50:]])
    except Exception as e:
        log(f"revive: stats fetch failed ({e})")
        return
    stuck = [v for v in candidates[-50:] if int((stats.get(v["video_id"]) or {}).get("viewCount", 0)) < floor]
    for v in stuck[:max_videos]:
        try:
            prompt = (f"This YouTube Short underperformed. Old title: '{v['title']}'. "
                      f"Topic: {v['topic']}. Write a NEW, completely different angle: "
                      f"title (using formulas like 'Why [Everyday Frustration]' or 'Why You Always [Do Something]', "
                      f"do not use colons or categories, end with one emoji, under 80 chars) and a 2-sentence description "
                      f"in the format: 'This isn't an accident. [Subject] uses [concrete design choice/layout] to [psychological effect].'\n"
                      'Respond ONLY with JSON: {"title": "...", "description": "..."}')
            key = cfg.get("gemini_api_key", "")
            fresh = scriptgen._call(key, prompt, 0.9)
            upload.update_snippet(v["video_id"], fresh["title"][:95], fresh["description"][:1000])
            revived.add(v["video_id"])
            log(f"revived {v['video_id']}: '{v['title']}' -> '{fresh['title']}'")
        except Exception as e:
            log(f"revive failed for {v['video_id']} (non-fatal): {e}")
    _save(REVIVED_FILE, sorted(revived))


# ---------------------------------------------------------------- comment drafts
def draft_replies(cfg: dict, log=print, max_drafts: int = 15):
    """Weekly: draft on-brand replies to new comments into reply_drafts.txt.
    Review the file, delete lines you don't want, then run: python post_replies.py"""
    try:
        threads = upload.fetch_recent_comments(max_results=max_drafts)
    except Exception as e:
        log(f"comment fetch failed ({e})")
        return
    if not threads:
        return
    drafted = []
    key = cfg.get("gemini_api_key", "")
    for t in threads:
        try:
            prompt = (f"You run a cinematic documentary channel about hidden reasons. A viewer commented: "
                      f'"{t["text"]}" on the video "{t["video_title"]}". Write one short, '
                      f"friendly, on-brand reply (max 25 words, can be playful or add a bonus fact). "
                      'Respond ONLY with JSON: {"reply": "..."}')
            reply = scriptgen._call(key, prompt, 0.7)["reply"]
            drafted.append(f"{t['comment_id']} ||| {reply}")
        except Exception:
            continue
    if drafted:
        with open(DRAFTS_FILE, "w", encoding="utf-8") as f:
            f.write("# Review these drafts. DELETE any line you don't want posted,\n"
                    "# then run: python post_replies.py\n")
            f.write("\n".join(drafted) + "\n")
        log(f"{len(drafted)} reply drafts written to {DRAFTS_FILE} for your review")


# ---------------------------------------------------------------- weekly trigger
def run_weekly_tasks(cfg: dict, log=print):
    """Called by run_daily: fires revive + comment drafts at most every 6 days."""
    last = _load(LAST_BOOST_FILE, {}).get("last")
    today = dt.date.today()
    if last and (today - dt.date.fromisoformat(last)).days < 6:
        return
    _save(LAST_BOOST_FILE, {"last": today.isoformat()})
    log("running weekly boost tasks (audit + revive + comment drafts + insight report)...")
    audit_public_metadata(log)
    revive(cfg, log)
    draft_replies(cfg, log)
    # Generate the plain-English insight report so the week's data becomes actionable.
    # Non-fatal: a report failure never blocks the run.
    try:
        import weekly_report
        report_text = weekly_report.build_report(save=True)
        log("Wrote weekly_report.txt - what's retaining, what's dying, what to make more of.")
        # ALSO push it to Discord so the best insight artifact actually reaches you, instead of
        # silently sitting in a local .txt. Force-send so alert_only_on_failure doesn't drop it.
        try:
            import alerts
            if not isinstance(report_text, str) or not report_text.strip():
                with open("weekly_report.txt", encoding="utf-8") as _rf:
                    report_text = _rf.read()
            if report_text and report_text.strip():
                alerts.notify(cfg, "Hidden Logic - Weekly Insight", report_text[:1800], is_failure=True)
        except Exception as _se:
            log(f"weekly report Discord send skipped (non-fatal): {_se}")
    except Exception as e:
        log(f"weekly report failed (non-fatal): {e}")

    # Calibration: validate the engine's self-scores (predicted views/retention/identity)
    # against ACTUAL performance. This was built but NEVER run; without it the hard >=8
    # prediction gates were never checked against reality. Non-fatal.
    try:
        import calibration_report
        calibration_report.main()
        log("Calibration report refreshed (predicted-vs-actual accuracy).")
    except SystemExit:
        pass   # calibration calls sys.exit when there's not enough data yet
    except Exception as e:
        log(f"calibration report skipped (non-fatal): {e}")


# ---------------------------------------------------------------- self-defense
import difflib
import re as _re

_MOJIBAKE_MARKERS = ("\u00c3", "\u00e2", "\u00c2", "\u00f0\u0178", "\u00f0\u0159")
_STOPWORDS = {"the","a","an","of","who","that","in","at","to","from","for","and",
              "with","his","her","their","nobody","ever","one"}


def fix_mojibake(s: str) -> str:
    """Repair UTF-8 text that was wrongly decoded as cp1252 (e.g. 'âš½' -> '⚽')."""
    if not any(m in s for m in _MOJIBAKE_MARKERS):
        return s
    for codec in ("cp1252", "latin-1"):
        try:
            fixed = s.encode(codec).decode("utf-8")
            if fixed != s:
                return fixed
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


def sync_channel_index(log=print):
    """Merge the channel's REAL uploads into the local index, so sequels and
    revives can see videos the pipeline didn't record (or that predate it)."""
    try:
        live = upload.list_uploads()
    except Exception as e:
        log(f"index sync skipped ({e})")
        return
    idx = _load(INDEX_FILE, [])
    known = {v["video_id"] for v in idx}
    added = 0
    for v in live:
        if "Hidden Logic Weekly" in v.get("title", ""):
            continue  # compilations are not Shorts; keep them away from sequels/revive
        if v["video_id"] not in known:
            idx.append({"video_id": v["video_id"], "title": fix_mojibake(v["title"]),
                        "topic": v["title"], "date": v["published"], "n": 0})
            added += 1
    if added:
        _save(INDEX_FILE, idx)
        log(f"index sync: adopted {added} video(s) the index didn't know about")


def audit_public_metadata(log=print):
    """Scan LIVE titles/descriptions for mojibake and leaked internal text;
    auto-repair via the API. Catches anything that ever slips through."""
    markers = ("factcheck", "quality score", "review pass", "[scriptgen]", "[tts]")
    try:
        live = upload.list_uploads()
    except Exception as e:
        log(f"metadata audit skipped ({e})")
        return
    for v in live:
        new_title = fix_mojibake(v["title"])
        desc = v["description"]
        new_desc = fix_mojibake(desc)
        if any(m in new_desc.lower() for m in markers):
            new_desc = "\n".join(l for l in new_desc.splitlines()
                                  if not any(m in l.lower() for m in markers)).strip()
        if new_title != v["title"] or new_desc != desc:
            try:
                upload.update_snippet(v["video_id"], new_title[:95], new_desc[:1000])
                log(f"metadata audit: repaired {v['video_id']} ('{v['title']}' -> '{new_title}')")
            except Exception as e:
                log(f"metadata audit: repair failed for {v['video_id']} ({e})")


def _sig_words(title: str) -> set:
    words = _re.findall(r"[a-z0-9]+", title.lower())
    return {w[:4].rstrip("s") for w in words if w not in _STOPWORDS and len(w) > 2}


def is_duplicate_title(title: str, days: int = 60) -> str | None:
    """Returns the clashing existing title only if the new one truly covers the same
    story (same subject AND substantially the same facts). Sharing a subject alone
    (another Drogba angle) or a shock phrase alone ('ZERO goals') is NOT a duplicate."""
    import datetime as _dt
    import re as _re
    cutoff = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    
    clean_new = _re.sub(r"\s*#.*$", "", title).strip()
    new_words = _sig_words(clean_new)
    new_lead = clean_new.split(":")[0].strip().lower()
    
    for v in _load(INDEX_FILE, []):
        if v.get("date", "") < cutoff:
            continue
        old = v["title"]
        clean_old = _re.sub(r"\s*#.*$", "", old).strip()
        old_words = _sig_words(clean_old)
        
        if not new_words or not old_words:
            continue
        jaccard = len(new_words & old_words) / len(new_words | old_words)
        same_lead = clean_old.split(":")[0].strip().lower() == new_lead
        ratio = difflib.SequenceMatcher(None, clean_new.lower(), clean_old.lower()).ratio()
        # Same subject is only a duplicate if the FACTS also overlap a lot - otherwise
        # it's just another angle on the same player (which we want to allow). Without
        # the lead match, only a very high overall similarity counts as a dup, so a
        # shared shock phrase ("ZERO goals") across different subjects does NOT trip it.
        if same_lead and new_lead and jaccard >= 0.55:
            return old
        if ratio >= 0.78:
            return old
    return None
