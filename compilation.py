"""
compilation.py - Weekly long-form: stitches the week's top Shorts into one
landscape video (blurred-pillarbox style) with chapter timestamps.
Opens the regular-video algorithm + builds watch hours toward the easier
monetization route (4,000 hours vs 10M Shorts views).
"""
import datetime as dt
import glob
import json
import os
import subprocess

import upload

WEEKLY_FILE = "weekly_compilations.json"


def _load():
    if os.path.exists(WEEKLY_FILE):
        with open(WEEKLY_FILE) as f:
            return json.load(f)
    return {"count": 0, "used_files": [], "last_week": ""}


def due_this_weekend() -> bool:
    """True on Saturday or Sunday if this ISO week's compilation hasn't run yet,
    so it fires the first weekend day the laptop is on and never twice."""
    today = dt.date.today()
    if today.weekday() not in (5, 6):  # Sat=5, Sun=6
        return False
    return _load().get("last_week", "") != f"{today.isocalendar()[0]}-{today.isocalendar()[1]}"


def _save(d):
    with open(WEEKLY_FILE, "w") as f:
        json.dump(d, f, indent=2)


def _candidates(days: int = 7) -> list[dict]:
    """Local short.mp4 files from the last N days, with their titles."""
    cutoff = dt.date.today() - dt.timedelta(days=days)
    out = []
    for meta_path in glob.glob(os.path.join("output", "*", "meta.json")):
        folder = os.path.dirname(meta_path)
        stamp = os.path.basename(folder).split("_")[0]
        try:
            d = dt.datetime.strptime(stamp, "%Y%m%d").date()
        except ValueError:
            continue
        video = os.path.join(folder, "short.mp4")
        if d >= cutoff and os.path.exists(video):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            out.append({"file": video, "title": meta.get("title", "Football fact")})
    return out


def _rank_by_views(cands: list[dict]) -> list[dict]:
    """Match local files to live videos via the channel index, rank by views."""
    try:
        idx = json.load(open("channel_index.json"))
        title_to_id = {v["title"]: v["video_id"] for v in idx}
        ids = [title_to_id[c["title"]] for c in cands if c["title"] in title_to_id]
        stats = upload.video_stats(ids) if ids else {}
        for c in cands:
            c["views"] = int((stats.get(title_to_id.get(c["title"], "")) or {}).get("viewCount", 0))
    except Exception:
        for c in cands:
            c["views"] = 0
    return sorted(cands, key=lambda c: -c["views"])


def _duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(out.stdout.strip())


def build(files: list[str], out_path: str):
    """Concat vertical Shorts onto a 1920x1080 canvas with blurred sides."""
    cmd = ["ffmpeg", "-y"]
    for f in files:
        cmd += ["-i", f]
    fc, labels = [], []
    for i in range(len(files)):
        fc.append(
            f"[{i}:v]split[s{i}a][s{i}b];"
            f"[s{i}a]scale=1920:1080,boxblur=24:4,setsar=1[bg{i}];"
            f"[s{i}b]scale=-2:1080,setsar=1[fg{i}];"
            f"[bg{i}][fg{i}]overlay=(W-w)/2:0,fps=30,format=yuv420p[v{i}];"
            f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    fc.append("".join(labels) + f"concat=n={len(files)}:v=1:a=1[v][a]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", out_path]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("compilation ffmpeg failed:\n" + proc.stderr[-1500:])
    return out_path


def run_weekly_compilation(cfg: dict, log=print, top_n: int = 6):
    state = _load()
    cands = [c for c in _candidates() if c["file"] not in state["used_files"]]
    cands = _rank_by_views(cands)[:top_n]
    if len(cands) < 3:
        log("compilation: fewer than 3 fresh Shorts this week, skipping")
        return
    files = [c["file"] for c in cands]
    out = os.path.join("output", f"weekly_{dt.date.today():%Y%m%d}.mp4")
    log(f"compilation: stitching {len(files)} top Shorts...")
    build(files, out)

    # chapters for the description (long-form SEO + navigation)
    chapters, t = [], 0.0
    for c in cands:
        mm, ss = int(t // 60), int(t % 60)
        chapters.append(f"{mm}:{ss:02d} {c['title']}")
        t += _duration(c["file"])
    n = state["count"] + 1
    title = f"The Best Hidden Logic Facts This Week 🤯 | Hidden Logic Weekly #{n}"
    description = ("The week's wildest everyday psychological mysteries in one video.\n\n"
                   + "\n".join(chapters)
                   + "\n\nNew glitches explained every single day - subscribe so you don't miss one."
                   + "\n\n#hiddenlogic #psychology #hiddenlogicfacts")
    url = upload.upload(out, title, description, ["#hiddenlogic", "#psychology", "#hiddenlogicfacts"])
    log(f"compilation uploaded: {url}")
    state["count"] = n
    today = dt.date.today()
    state["last_week"] = f"{today.isocalendar()[0]}-{today.isocalendar()[1]}"
    state["used_files"] += files
    state["used_files"] = state["used_files"][-100:]
    _save(state)
