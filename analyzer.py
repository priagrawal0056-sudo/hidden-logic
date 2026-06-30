"""
analyzer.py - Daily learning loop. Before production, studies how past POOL videos
performed and writes a short content brief that biases the day's topic/format choices
toward what's working and away from what isn't.

Optimizes for ENGAGEMENT RATE (likes+comments per view), NOT raw views - per the
research, view-count is a vanity metric and chasing it amplifies failing videos.
Retention (the strongest signal) is an optional upgrade: if the Analytics API scope
is available it's folded in, otherwise engagement carries the loop with zero re-auth.

Guardrails: minimum sample before trusting a pattern, ~30% exploration preserved,
brief only ADDS soft guidance, fully non-fatal.
"""
import datetime as dt
import json
import os
import re

import upload

BRIEF_FILE = "content_brief.json"
MIN_VIDEOS_PER_PATTERN = 3      # don't trust a trait seen fewer times
MIN_VIEWS_PER_PATTERN = 100     # ...or with too little exposure
MATURE_DAYS = 2                 # videos younger than this lack stable data


def _load_index() -> list:
    if os.path.exists("channel_index.json"):
        with open("channel_index.json") as f:
            return json.load(f)
    return []


def _subject(title: str) -> str:
    """The part before the colon is the searchable subject (player/nation/event)."""
    return title.split(":")[0].strip().lower() if ":" in title else ""


def _hook_type(title: str) -> str:
    """Classify the title's hook structure (the part after the colon usually carries it)."""
    hook = title.split(":", 1)[1].lower() if ":" in title else title.lower()
    if "?" in hook:
        return "question"
    if re.search(r"\d", hook):
        return "number"          # stat/number-led
    if any(w in hook for w in ("only", "never", "first", "last", "most", "nobody", "secret")):
        return "bold_claim"
    return "plain"


def _traits(title: str, topic: str) -> dict:
    """Dimensions we control and can therefore learn from."""
    t = (title + " " + topic).lower()
    fmt = "story"
    if any(w in t for w in ("quiz", "guess", "can you name", "which")):
        fmt = "quiz"
    elif any(w in t for w in ("vs ", " v ", "ranked", "top ", "countdown")):
        fmt = "ranking"
    elif any(w in t for w in ("record", "stat", "number", "goals", "youngest", "oldest", "fastest")):
        fmt = "record"
    era = "modern" if re.search(r"20(1[0-9]|2[0-6])", t) else ("classic" if re.search(r"19\d\d|200[0-9]", t) else "unspecified")
    return {"format": fmt, "era": era, "subject": _subject(title), "hook": _hook_type(title)}


_RET_INSIGHT_CACHE = {"date": None, "text": ""}
_BENCHMARK_CACHE = {"date": None, "text": ""}


def cached_rater_benchmark(cfg: dict, log=print) -> str:
    today = dt.date.today().isoformat()
    if _BENCHMARK_CACHE["date"] != today:
        try:
            _BENCHMARK_CACHE["text"] = rater_benchmark(cfg, log)
        except Exception:
            _BENCHMARK_CACHE["text"] = ""
        _BENCHMARK_CACHE["date"] = today
    return _BENCHMARK_CACHE["text"]


def cached_retention_insight(cfg: dict, log=print) -> str:
    today = dt.date.today().isoformat()
    if _RET_INSIGHT_CACHE["date"] != today:
        try:
            _RET_INSIGHT_CACHE["text"] = retention_insight(cfg, log)
        except Exception:
            _RET_INSIGHT_CACHE["text"] = ""
        _RET_INSIGHT_CACHE["date"] = today
    return _RET_INSIGHT_CACHE["text"]


def analyze(cfg: dict, log=print) -> dict | None:
    """Pull stats for mature pool videos, rank by engagement rate, extract patterns."""
    idx = _load_index()
    cutoff = (dt.date.today() - dt.timedelta(days=MATURE_DAYS)).isoformat()
    pool = [v for v in idx
            if v.get("source", "pool") == "pool"
            and v.get("date", "9999") <= cutoff
            and "Hidden Logic Weekly" not in v.get("title", "")]
    if len(pool) < MIN_VIDEOS_PER_PATTERN:
        log("analyzer: not enough mature pool videos yet, skipping (normal early on)")
        return None
    ids = [v["video_id"] for v in pool[-50:]]
    try:
        stats = upload.video_stats(ids)
    except Exception as e:
        log(f"analyzer: stats fetch failed, skipping ({e})")
        return None
    # retention is the primary signal now (the algorithm's real currency).
    retention = {}
    try:
        retention = upload.video_retention(ids)  # {video_id: avg view %}
    except Exception as e:
        log(f"analyzer: retention fetch failed, falling back to engagement only ({e})")

    scored = []
    for v in pool[-50:]:
        s = stats.get(v["video_id"], {})
        if isinstance(s, str):
            views, likes, comments = int(s or 0), 0, 0
        else:
            views = int(s.get("viewCount", 0))
            likes = int(s.get("likeCount", 0))
            comments = int(s.get("commentCount", 0))
        if views < 20:
            continue
        eng = (likes + comments) / views
        ret = retention.get(v["video_id"])  # 0-100 or None
        # blended score: retention dominates when available, engagement fills in.
        # normalize retention to 0-1; engagement is already a small ratio.
        score = (ret / 100.0 * 0.8 + min(eng, 0.1) / 0.1 * 0.2) if ret is not None else eng
        scored.append({**v, "views": views, "eng": eng, "retention": ret, "score": score,
                       **_traits(v["title"], v.get("topic", ""))})
    if len(scored) < MIN_VIDEOS_PER_PATTERN:
        log("analyzer: too few videos with usable data, skipping")
        return None

    median_score = sorted(s["score"] for s in scored)[len(scored) // 2]

    def pattern_winners(dim: str) -> dict:
        groups: dict = {}
        for s in scored:
            groups.setdefault(s[dim], []).append(s)
        out = {}
        for key, vids in groups.items():
            if not key or len(vids) < MIN_VIDEOS_PER_PATTERN:
                continue
            if sum(v["views"] for v in vids) < MIN_VIEWS_PER_PATTERN:
                continue
            out[key] = sum(v["score"] for v in vids) / len(vids)
        return out

    fmt_perf = pattern_winners("format")
    era_perf = pattern_winners("era")
    hook_perf = pattern_winners("hook")  # which hook structures retain best
    # top individual subjects by engagement (these become sequel/topic suggestions)
    _FMT_WORDS = {"quiz", "guess", "ranking", "record", "story", "which", "can you name"}
    top_subjects = []
    for s in sorted(scored, key=lambda x: -x["score"])[:8]:
        subj = s["subject"]
        if subj and s["score"] >= median_score and subj not in _FMT_WORDS and subj not in top_subjects:
            top_subjects.append(subj)
        if len(top_subjects) >= 5:
            break

    rets = [s["retention"] for s in scored if s["retention"] is not None]
    avg_ret = round(sum(rets) / len(rets), 1) if rets else None

    brief = {
        "date": dt.date.today().isoformat(),
        "sample_size": len(scored),
        "avg_retention": avg_ret,
        "best_formats": sorted(fmt_perf, key=lambda k: -fmt_perf[k])[:2],
        "weak_formats": [k for k in fmt_perf if fmt_perf[k] < median_score * 0.6],
        "best_eras": sorted(era_perf, key=lambda k: -era_perf[k])[:1],
        "best_hooks": sorted(hook_perf, key=lambda k: -hook_perf[k])[:2],
        "hot_subjects": top_subjects,
    }
    _write(brief)
    ret_msg = f", avg retention {avg_ret}%" if avg_ret is not None else " (retention pending)"
    log(f"analyzer: brief from {len(scored)} videos{ret_msg} - "
        f"best hooks {brief['best_hooks']}, best formats {brief['best_formats']}, "
        f"hot subjects {top_subjects[:3]}")
    return brief


def _write(brief: dict):
    with open(BRIEF_FILE, "w") as f:
        json.dump(brief, f, indent=2)


def todays_brief() -> dict | None:
    if not os.path.exists(BRIEF_FILE):
        return None
    with open(BRIEF_FILE) as f:
        b = json.load(f)
    return b if b.get("date") == dt.date.today().isoformat() else None


def brief_prompt_snippet() -> str:
    """The soft guidance injected into the writer. Empty string if no fresh brief."""
    b = todays_brief()
    if not b:
        return ""
    parts = []
    if b.get("best_formats"):
        parts.append(f"formats performing best lately: {', '.join(b['best_formats'])}")
    if b.get("weak_formats"):
        parts.append(f"underperforming (use sparingly): {', '.join(b['weak_formats'])}")
    if b.get("best_eras"):
        parts.append(f"strongest era angle: {b['best_eras'][0]}")
    if b.get("best_hooks"):
        hook_label = {"number":"number/stat-led hooks", "question":"question hooks",
                      "bold_claim":"bold-claim hooks (only/never/first/secret)", "plain":"direct hooks"}
        labels = [hook_label.get(h, h) for h in b["best_hooks"]]
        parts.append(f"hook styles retaining best: {', '.join(labels)}")
    if b.get("hot_subjects"):
        parts.append(f"subjects driving engagement: {', '.join(b['hot_subjects'][:3])}")
    if not parts:
        return ""
    return ("\n\nDATA SIGNAL (from this channel's OWN recent retention data - this is real "
            "performance, weight it heavily): " + "; ".join(parts) + ". "
            "Lean toward the best-performing formats/hooks/subjects above. "
            "AVOID the underperforming formats unless the topic genuinely demands one - "
            "they have measurably lost this channel views. Keep enough variety to stay fresh, "
            "but treat this signal as evidence, not a loose suggestion.")


def analysis_topic() -> str | None:
    """A topic built from the best-performing subject the analyzer surfaced,
    for the dedicated analysis-driven daily slot. None if no fresh brief."""
    b = todays_brief()
    if not b or not b.get("hot_subjects"):
        return None
    subj = b["hot_subjects"][0]
    fmt = (b.get("best_formats") or ["story"])[0]
    return (f"ANALYSIS-DRIVEN video: this channel's data shows '{subj}' and the "
            f"'{fmt}' format are driving the most engagement right now. Make a fresh, "
            f"NON-duplicate {fmt}-style video about {subj} (a different angle than before), "
            f"engineered to repeat that success. Title starts with the subject's name.")


def retention_insight(cfg: dict, log=print) -> str:
    """Analyze the retention CURVE of a few top videos to find the channel's
    common drop-off point, and return one guidance line for the writer. Cheap:
    one API call per sampled video, capped at 5. Empty string on no data."""
    import upload
    idx = _load_index()
    cutoff = (dt.date.today() - dt.timedelta(days=MATURE_DAYS)).isoformat()
    pool = [v for v in idx if v.get("source", "pool") == "pool"
            and v.get("date", "9999") <= cutoff
            and "Hidden Logic Weekly" not in v.get("title", "")]
    if len(pool) < MIN_VIDEOS_PER_PATTERN:
        return ""
    # sample the most recent few (freshest curves), cap at 5 to stay quota-safe
    sample = pool[-5:]
    early_drops = []
    for v in sample:
        curve = []
        try:
            curve = upload.retention_curve(v["video_id"])
        except Exception:
            pass
        if not curve:
            continue
        # find the first elapsed ratio where watch_ratio falls below 0.5 (half gone)
        for ratio, watch in curve:
            if watch < 0.5:
                early_drops.append(ratio)
                break
    if len(early_drops) < 2:
        return ""
    avg_drop = sum(early_drops) / len(early_drops)
    pct = int(avg_drop * 100)
    if avg_drop < 0.25:
        where = (f"viewers tend to drop in the FIRST QUARTER (around {pct}% in) - the hook "
                 f"and opening fact must hit faster; front-load the most shocking detail.")
    elif avg_drop < 0.6:
        where = (f"viewers hold through the opening but fall off near the MIDDLE (around {pct}% in) "
                 f"- tighten the middle, move the twist earlier, keep the like-CTA from stalling pace.")
    else:
        where = (f"retention stays strong past the midpoint (half-audience around {pct}% in) "
                 f"- the structure works; keep doing this.")
    log(f"retention insight: half-audience point ~{pct}% through")
    return "\n\nRETENTION SIGNAL (from this channel's own drop-off curves): " + where


def rater_benchmark(cfg: dict, log=print) -> str:
    """Build a calibration reference for the script rater from REAL channel data:
    the hook openings of top performers vs weak ones, by retention+engagement.
    Injected into the review prompt so scoring is anchored to what actually worked
    on THIS channel, not generic criteria. Empty string if not enough data."""
    import upload
    idx = _load_index()
    cutoff = (dt.date.today() - dt.timedelta(days=MATURE_DAYS)).isoformat()
    pool = [v for v in idx if v.get("source", "pool") == "pool"
            and v.get("date", "9999") <= cutoff
            and "Hidden Logic Weekly" not in v.get("title", "")]
    if len(pool) < 6:
        return ""
    ids = [v["video_id"] for v in pool[-50:]]
    try:
        stats = upload.video_stats(ids)
    except Exception:
        return ""
    retention = {}
    try:
        retention = upload.video_retention(ids)
    except Exception:
        pass

    scored = []
    for v in pool[-50:]:
        s = stats.get(v["video_id"], {})
        views = int(s.get("viewCount", 0)) if isinstance(s, dict) else int(s or 0)
        if views < 50:
            continue
        likes = int(s.get("likeCount", 0)) if isinstance(s, dict) else 0
        comments = int(s.get("commentCount", 0)) if isinstance(s, dict) else 0
        eng = (likes + comments) / views
        ret = retention.get(v["video_id"])
        score = (ret / 100.0 * 0.8 + min(eng, 0.1) / 0.1 * 0.2) if ret is not None else eng
        scored.append({"title": v["title"], "views": views, "ret": ret, "score": score})
    if len(scored) < 6:
        return ""

    scored.sort(key=lambda x: -x["score"])
    n = max(2, len(scored) // 4)
    winners = scored[:n]
    losers = scored[-n:]

    def fmt(v):
        title = v["title"].split("#")[0].strip()
        r = f"{int(v['ret'])}% retention" if v["ret"] is not None else f"{v['views']} views"
        return f'  - "{title}" ({r})'

    lines = ["\n\nCALIBRATION (this channel's REAL performance - score against THIS standard, "
             "not generic rules):",
             "TOP performers (these are what an 8-10 looks like HERE):"]
    lines += [fmt(v) for v in winners]
    lines += ["WEAK performers (these are 3-5 - avoid what they did):"]
    lines += [fmt(v) for v in losers]
    lines.append("Score the new script by how closely it resembles the TOP set's hook style, "
                 "specificity, and payoff - reward what demonstrably worked here.")
    return "\n".join(lines)
