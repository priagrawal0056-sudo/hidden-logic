"""
video_context.py - lightweight per-video context store.

The comment-reply system previously only knew a video's TITLE, so on vague comments
("nice", "lol", "wrong") the model had nothing concrete to anchor to and improvised
off-topic replies. This stores the real context (script, visual_thesis, topic) keyed
by YouTube video id at upload time, so replies can be grounded in what the video
actually said.

Store is a single JSON file: { "<video_id>": {title, topic, visual_thesis, script}, ... }
Self-trimming so it never grows unbounded. All operations are non-fatal by design.
"""
import json
import os

CONTEXT_FILE = "video_context.json"
MAX_ENTRIES = 600          # plenty for an active channel; oldest are trimmed
MAX_SCRIPT_CHARS = 1200    # we only need enough to ground a reply, not the whole thing


def _load() -> dict:
    if not os.path.exists(CONTEXT_FILE):
        return {}
    try:
        with open(CONTEXT_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_context(video_id: str, meta: dict) -> None:
    """Record the context for a freshly uploaded video. Non-fatal."""
    if not video_id:
        return
    try:
        store = _load()
        store[video_id] = {
            "title": (meta.get("title") or "")[:200],
            "topic": (meta.get("topic") or "")[:200],
            "visual_thesis": (meta.get("visual_thesis") or "")[:500],
            "script": (meta.get("script") or "")[:MAX_SCRIPT_CHARS],
        }
        # trim oldest if we exceed the cap (dict preserves insertion order in py3.7+)
        if len(store) > MAX_ENTRIES:
            for k in list(store.keys())[: len(store) - MAX_ENTRIES]:
                store.pop(k, None)
        tmp = CONTEXT_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONTEXT_FILE)
    except Exception:
        pass  # never block the pipeline over context bookkeeping


def get_context(video_id: str) -> dict:
    """Return stored context for a video id, or {} if unknown. Non-fatal."""
    if not video_id:
        return {}
    try:
        return _load().get(video_id, {})
    except Exception:
        return {}
