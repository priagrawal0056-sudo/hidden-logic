"""
post_replies.py - auto-reply to recent comments in the channel's PUNDIT voice.

Full-auto: reads recent comments, drafts a short reply for each with the LLM (in The Pundit
persona - confident, a bit cheeky, banters about the topic takes but never at the person), and
posts it. Built to MAXIMIZE engagement (replies broadly) while keeping safety rails:
  - never replies to the same comment twice (tracks replied ids in replies_done.json)
  - skips genuinely toxic/abusive comments (don't feed trolls, don't get the channel flagged)
  - never gets personal/insulting toward the commenter (provocative about the topic only)
  - rate-capped per run so a burst of comments can't look like spam to YouTube
  - every step is non-fatal: a failure here never breaks the video pipeline

Run standalone:   python post_replies.py
Or it runs automatically at the end of each daily run (wired in run_daily.py).
"""
import json
import os
import re
import time

REPLIED_FILE = "replies_done.json"
REPLY_COUNT_FILE = "reply_daily_count.json"   # {date: count} to enforce a per-DAY ceiling
MAX_REPLIES_PER_RUN = 12          # per-process cap
MAX_REPLIES_PER_DAY = 25          # hard daily ceiling across ALL runs (spam/strike safety)
MAX_REPLIES_PER_VIDEO = 2         # don't carpet-bomb one video's comment section
REPLY_SLEEP = 4.0                 # base seconds between posts (jittered below) - human-paced
_RAN_THIS_PROCESS = False         # the reply path is invoked twice per run; only act once

# comments containing these are skipped entirely (don't engage abuse / slurs / spam)
_TOXIC = re.compile(
    r"\b(kill yourself|kys|f[\W_]*a[\W_]*g|n[\W_]*i[\W_]*g|retard|"
    r"r[\W_]*a[\W_]*p[\W_]*e|whore|slut|subscribe to me|sub4sub|check out my|"
    r"free v[\-\s]?bucks|onlyfans|\.ru/|bit\.ly/|t\.me/)\b",
    re.I,
)


def _load_replied():
    if os.path.exists(REPLIED_FILE):
        try:
            return set(json.load(open(REPLIED_FILE, encoding="utf-8")))
        except Exception:
            return set()
    return set()


def _save_replied(ids):
    try:
        json.dump(sorted(ids)[-2000:], open(REPLIED_FILE, "w", encoding="utf-8"))
    except Exception:
        pass


def _today():
    import datetime as _dt
    return _dt.date.today().isoformat()


def _replies_today() -> int:
    try:
        if os.path.exists(REPLY_COUNT_FILE):
            d = json.load(open(REPLY_COUNT_FILE, encoding="utf-8"))
            return int(d.get(_today(), 0))
    except Exception:
        pass
    return 0


def _add_replies_today(n: int):
    try:
        prev = _replies_today()
        json.dump({_today(): prev + int(n)}, open(REPLY_COUNT_FILE, "w", encoding="utf-8"))
    except Exception:
        pass


# Low-value comments not worth a reply (cuts volume + the templated-reply spam fingerprint):
# very short, emoji-only, or generic one-word praise. We prioritise questions + substance.
_LOW_VALUE = re.compile(
    r"^(nice|cool|wow|lol+|lmao|first|early|w|fire|good|great|facts|true|real|same|relatable)\W*$",
    re.I,
)


def _is_low_value(text: str) -> bool:
    t = (text or "").strip()
    if "?" in t:
        return False                      # questions are always worth answering
    if len(t) < 12:
        return True                       # one-word / emoji-only
    if _LOW_VALUE.match(t):
        return True
    return False


REPLY_PROMPT = """You run a YouTube Shorts channel called Hidden Logic. Your \
whole brand is a calm, curious, slightly witty documentary creator who exposes the psychological quirks and mechanisms \
behind everyday frustrations and behaviors (Think: Vox, Johnny Harris). Now you're replying to a viewer's comment. \
Stay in that smart, engaging, documentary creator character, and keep the energy friendly, \
knowledgeable, warm, and genuinely curious - NEVER provocative, argumentative, or talking down to the viewer.

THE VIDEO THIS COMMENT IS ON (this is the context - the comment is almost always about THIS):
TITLE: \"\"\"{video_title}\"\"\"
WHAT THE VIDEO EXPLAINS (the actual reveal/mechanism): \"\"\"{video_context}\"\"\"

CONTEXT IS CRITICAL: read the title AND the explanation above and understand what the video is about FIRST. \
The viewer's comment is reacting to THAT video. Ground your reply in the SPECIFIC mechanism/reveal above - \
reference the actual system the video explained, not a generic guess. Do NOT invent a different topic, system, or \
niche that isn't in the context or comment. If the comment is vague ("nice", "wrong", "lol"), \
reply about the VIDEO'S specific subject and reveal. Never assume a specific match, sport, or soccer topic.

Rules for the reply:
- 1 sentence, max 18 words. Short, punchy, confident.
- It MUST make sense as a reply to a comment on THAT specific video. Stay on the video's topic.
- Stay in character: have a smart take, a little witty, never neutral or corporate.
- If they DISAGREE with you: warmly re-explain the video's system (mention the design trick), stay open and friendly, and invite their take rather than scoring a point.
- If they AGREE or praise: thank them genuinely, then add one more genuinely interesting detail about the topic.
- If they ask a question: answer it boldly and briefly, only if you're sure of the fact.
- If they're joking: match the energy, be funny.
- IF THEY CALL THE CHANNEL AI / A BOT / A ROBOT / FAKE / SAY THE VOICE IS AI: do NOT get defensive, do NOT confirm it, do NOT argue about whether you're a bot. Brush it off with confidence and pivot STRAIGHT back to the topic - the design takes are what matters. E.g. "the explanations are still better than yours - now what system should we dissect next?" Never engage on the "are you AI" topic itself.
- CRUCIAL: be warm and curious, never provocative, and never about the PERSON. Never insult, demean, or get personal. No slurs, nothing about their intelligence.
- End in a way that invites them to reply (a question back, asking what they've noticed) to drive comments.
- NEVER be defensive, preachy, or apologetic. No hashtags. At most one emoji if it fits.
- BANNED WORDS: Do NOT use the words "Hidden", "Secret", "Dark Design", "Manipulation", "Simulation", "Matrix", "Brainwashing", "Control", or "Conspiracy" in the reply.
- Use only plain punctuation. NEVER use em dashes or en dashes; use a comma or a full stop instead.

The viewer's comment:
\"\"\"{comment}\"\"\"

Respond with ONLY a JSON object: {{"reply": "your reply text here"}}"""


def _clean_reply(text: str) -> str:
    """Normalize a drafted reply: strip em/en dashes (standing channel preference) and tidy
    whitespace. Belt-and-suspenders so a posted reply never contains a dash even if the
    model ignores the prompt rule."""
    if not text:
        return text
    # em dash / en dash / horizontal bar -> comma+space (or just a space if already spaced)
    text = text.replace(" \u2014 ", ", ").replace(" \u2013 ", ", ")
    text = text.replace("\u2014", ", ").replace("\u2013", ", ").replace("\u2015", ", ")
    text = text.replace(" ,", ",").replace(",,", ",")
    return " ".join(text.split()).strip()


def _salvage_reply(raw: str) -> str:
    """Pull the reply text out of a model response even when the JSON is malformed - which
    happens when the reply itself contains unescaped inner quotes (the Pundit loves scare-
    quotes like that "legend"), breaking json.loads partway through. We try strict JSON
    first, then fall back to grabbing everything between the reply field and the final brace."""
    import json as _json
    import re as _re
    raw = (raw or "").strip()
    if not raw:
        return ""
    # 1) try strict JSON
    try:
        obj = _json.loads(raw)
        if isinstance(obj, dict):
            for k in ("reply", "text", "response", "content"):
                if obj.get(k):
                    return str(obj[k]).strip()
    except Exception:
        pass
    # 2) salvage: take everything after "reply": " up to the LAST quote before the final brace.
    # This recovers the full text even when inner quotes broke the parse.
    m = _re.search(r'"(?:reply|text|response|content)"\s*:\s*"(.+)"\s*[},]?\s*$',
                   raw, _re.DOTALL)
    if m:
        val = m.group(1)
        # unescape standard sequences; collapse stray inner quotes/newlines
        val = val.replace('\\"', '"').replace("\\n", " ").replace("\\/", "/").replace("\\\\", "\\")
        return val.strip().rstrip('"').strip()
    # 3) last resort: if it's just bare text (no JSON at all), use it as-is
    if not raw.startswith("{"):
        return raw.strip().strip('"')
    return ""


def _draft_reply(api_key: str, comment_text: str, video_title: str = "", video_context: str = "") -> str:
    """Draft a single reply via the LLM (uses scriptgen's provider + failover). The provider
    returns JSON, but the reply text often contains inner quotes that break strict JSON
    parsing, so we salvage the text robustly rather than dropping/truncating it. The video
    title AND the actual reveal/mechanism are passed as context so the reply matches what the
    video is actually about, even when the comment itself is vague."""
    import scriptgen
    prompt = REPLY_PROMPT.format(comment=comment_text[:500],
                                 video_title=(video_title or "Unknown - reply generically about the topic, do not assume a specific match or result")[:200],
                                 video_context=(video_context or "No extra context available - rely on the title only and stay general.")[:900])
    try:
        data = scriptgen._call(api_key, prompt, temperature=0.9)
        if isinstance(data, dict):
            if data.get("_raw"):                 # claude_code couldn't parse - salvage text
                return _clean_reply(_salvage_reply(str(data["_raw"])))
            for k in ("reply", "text", "response", "content"):
                if data.get(k):
                    return _clean_reply(str(data[k]).strip().strip('"'))
            vals = [v for v in data.values() if isinstance(v, str) and v.strip()]
            if vals:
                return _clean_reply(vals[0].strip().strip('"'))
        # data came back as a string (or odd shape) - salvage the reply text from it
        return _clean_reply(_salvage_reply(str(data)))
    except Exception:
        return ""


GENERIC_FALLBACKS = [
    "That's exactly what the design wants you to think. What everyday mystery should we explain next?",
    "Interesting point. But once you notice the brain glitch, you'll see it everywhere.",
    "Exactly. We're all playing by their rules. What system should we dissect next?",
]


def run_auto_replies(cfg: dict, log=print, max_replies: int = MAX_REPLIES_PER_RUN) -> int:
    # Config kill-switch: set "auto_replies": false in config.json to disable this feature
    # entirely (no comment fetching, no replies). Defaults to True to preserve old behavior.
    if not cfg.get("auto_replies", True):
        log("auto-replies: disabled in config (auto_replies=false)")
        return 0
    """Read recent comments, draft + post replies in the channel voice. Returns how many
    were posted. Non-fatal: returns the count so far on any error."""
    global _RAN_THIS_PROCESS
    if _RAN_THIS_PROCESS:
        # the pipeline invokes this twice per run; only act once so we never double-post.
        return 0
    _RAN_THIS_PROCESS = True
    # hard per-DAY ceiling across all runs (the main spam/strike safeguard)
    day_remaining = MAX_REPLIES_PER_DAY - _replies_today()
    if day_remaining <= 0:
        log(f"auto-replies: daily cap reached ({MAX_REPLIES_PER_DAY}); skipping")
        return 0
    max_replies = min(max_replies, day_remaining)
    try:
        import upload
    except Exception as e:
        log(f"auto-replies: upload module unavailable ({e})")
        return 0
    api_key = cfg.get("gemini_api_key", "")
    try:
        comments = upload.fetch_recent_comments(max_results=50)
    except Exception as e:
        log(f"auto-replies: couldn't fetch comments ({e})")
        return 0
    if not comments:
        log("auto-replies: no comments to reply to")
        return 0

    replied = _load_replied()
    posted = 0
    per_video = {}
    import random
    for c in comments:
        cid = c.get("comment_id")
        text = (c.get("text") or "").strip()
        if not cid or cid in replied or not text:
            continue
        if _TOXIC.search(text):
            log(f"auto-replies: skipped a toxic/spam comment ({cid[:12]})")
            replied.add(cid)          # mark so we don't re-evaluate it
            continue
        if _is_low_value(text):
            replied.add(cid)          # one-word/emoji praise: not worth a reply, mark handled
            continue
        vid_id = (c.get("video_id") or "").strip()
        if vid_id and per_video.get(vid_id, 0) >= MAX_REPLIES_PER_VIDEO:
            continue                  # don't carpet-bomb a single video's comments
        if posted >= max_replies:
            log(f"auto-replies: hit cap ({max_replies}), stopping")
            break

        vid_title = (c.get("video_title") or "").strip()
        # Pull the stored context (script + visual thesis) for this video so the reply is
        # grounded in the actual reveal, not just the title. Falls back gracefully.
        vid_ctx = ""
        try:
            import video_context as _vc
            ctx_data = _vc.get_context((c.get("video_id") or "").strip())
            if ctx_data:
                bits = []
                if ctx_data.get("visual_thesis"):
                    bits.append("Reveal: " + ctx_data["visual_thesis"])
                if ctx_data.get("script"):
                    bits.append("Script: " + ctx_data["script"])
                vid_ctx = "  ".join(bits)
        except Exception:
            vid_ctx = ""
        reply = _draft_reply(api_key, text, vid_title, vid_ctx) or random.choice(GENERIC_FALLBACKS)
        reply = reply.replace("\n", " ").strip()[:240]   # keep it tidy & within limits
        try:
            upload.post_reply(cid, reply)
            posted += 1
            per_video[vid_id] = per_video.get(vid_id, 0) + 1
            replied.add(cid)
            # log the FULL reply + the video context so wrong-context replies are visible
            ctx = (vid_title[:40] + "...") if len(vid_title) > 40 else (vid_title or "?")
            log(f"auto-replies: [{ctx}] {cid[:8]} ({len(reply)} chars) -> {reply}")
            time.sleep(REPLY_SLEEP + random.uniform(0.5, 3.5))   # jitter: avoid a robotic cadence
        except Exception as e:
            log(f"auto-replies: failed to post to {cid[:12]} ({e})")

    _save_replied(replied)
    if posted:
        _add_replies_today(posted)
    log(f"auto-replies: posted {posted} repl{'y' if posted == 1 else 'ies'}")
    return posted


if __name__ == "__main__":
    if not os.path.exists("config.json"):
        raise SystemExit("config.json not found - run from the footy-shorts folder.")
    cfg = json.load(open("config.json", encoding="utf-8"))
    run_auto_replies(cfg)
