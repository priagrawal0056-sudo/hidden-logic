"""
visuals.py - Hidden Logic
Streams MULTIPLE free portrait clips per video from Pexels + Pixabay, matched to the
script's b-roll keywords, so the final Short cuts between scenes like a real edit.
Ensures 1:1 mapping between the scene's requested keyword and the downloaded clip.
"""
import json
import os
import random
import time
import requests

SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"

_RATE_LIMITED: set = set()
CACHE_FILE = "used_clips.json"
_SCORE_CACHE: dict = {}

# Optional local proof-clip library: drop hand-picked portrait .mp4s into
# broll_library/<concept>/ (e.g. broll_library/driving/) and the pipeline will use them as a
# reliable, always-on-anchor fallback. Lets you permanently fix a weak niche.
BROLL_LIBRARY_DIR = "broll_library"

# Curated, scene-CONSISTENT proof-query banks per concept. Every query in a bank shows the SAME
# subject/setting, and each bank front-loads shots that VISUALLY PROVE the mechanism (not just
# scenery). Used to (a) supply anchor-consistent fallbacks and (b) inject a couple of proof
# shots, so a video never drifts to a different subject (a car video never cuts to a motorcycle).
SCENE_LIBRARY = {
    "driving": {
        "anchor": "a CAR being driven / car traffic (NOT a motorcycle, scooter, bicycle, boat, train or plane)",
        "queries": ["car driving pov dashboard highway", "car brake lights close up",
                    "cars bumper to bumper traffic jam", "rear view mirror car approaching",
                    "highway traffic cars", "car dashboard speedometer close up",
                    "cars driving close together", "traffic congestion cars"],
    },
    "supermarket": {
        "anchor": "a supermarket / grocery store interior",
        "queries": ["supermarket aisle wide shot", "grocery store shelves products",
                    "shopping cart pushing supermarket", "checkout counter groceries scanning",
                    "supermarket dairy fridge section", "person browsing supermarket shelves"],
    },
    "airport": {
        "anchor": "an airport terminal / air travel",
        "queries": ["airport terminal walking travelers", "airport departure board gates",
                    "airport gate waiting seats", "boarding pass close up hand",
                    "airplane window wing view", "luggage carousel baggage claim"],
    },
    "hotel": {
        "anchor": "a hotel interior",
        "queries": ["hotel hallway corridor doors", "hotel room bed white sheets",
                    "hotel lobby reception desk", "keycard hotel door opening"],
    },
    "restaurant": {
        "anchor": "a restaurant / dining setting",
        "queries": ["restaurant interior tables diners", "restaurant menu close up hands",
                    "waiter serving food restaurant", "fast food counter ordering"],
    },
    "elevator": {
        "anchor": "an elevator / lift interior",
        "queries": ["elevator interior doors closing", "elevator buttons panel close up",
                    "person waiting elevator lobby", "elevator mirror interior"],
    },
    "phone": {
        "anchor": "a smartphone / phone screen being used",
        "queries": ["person scrolling smartphone close up", "phone notification screen close up",
                    "hand holding phone texting", "smartphone app scrolling thumb"],
    },
    "money": {
        "anchor": "shopping / prices / paying",
        "queries": ["price tag close up store", "hand paying card contactless",
                    "cash register receipt printing", "sale discount tags shop"],
    },
}

_CONCEPT_KEYWORDS = {
    "driving": ["car", "drive", "driving", "traffic", "road", "highway", "lane", "tailgat",
                "brake", "steering", "speedometer", "commute", "merge", "windshield"],
    "supermarket": ["supermarket", "grocery", "groceries", "store", "aisle", "checkout", "cart",
                    "shelf", "shelves", "milk", "dairy"],
    "airport": ["airport", "flight", "plane", "airplane", "gate", "boarding", "terminal",
                "luggage", "airline", "flying"],
    "hotel": ["hotel", "lobby", "sheets", "hallway", "keycard"],
    "restaurant": ["restaurant", "menu", "diner", "waiter", "buffet", "cafe", "dining"],
    "elevator": ["elevator", "lift", "escalator"],
    "phone": ["phone", "smartphone", "app", "scroll", "notification", "swipe", "texting"],
    "money": ["price", "sale", "discount", "spend", "spending", "buy", "buying", "cost", ".99", "coupon"],
}


def _detect_concept(topic: str, keywords: list, visual_thesis: str = "") -> str | None:
    """Detect the video's dominant scene concept so ALL clips stay consistent (no car->motorcycle
    drift) and can be biased toward proof shots."""
    blob = " ".join([str(topic), str(visual_thesis)] + [str(k) for k in (keywords or [])]).lower()
    best, best_hits = None, 0
    for concept, kws in _CONCEPT_KEYWORDS.items():
        hits = sum(1 for k in kws if k in blob)
        if hits > best_hits:
            best, best_hits = concept, hits
    # Only lock a concept when it's clearly dominant (>=2 signal words); abstract topics
    # (memory/perception/social) stay unlocked so we don't force a wrong anchor on them.
    return best if best_hits >= 2 else None


def _library_clip(concept: str, downloaded_ids: set, dst_path: str) -> bool:
    """Copy a hand-picked local clip from broll_library/<concept>/ into dst_path if one is
    available and unused this video (portrait .mp4). Returns True on success."""
    if not concept:
        return False
    lib = os.path.join(BROLL_LIBRARY_DIR, concept)
    if not os.path.isdir(lib):
        return False
    import shutil
    for fn in sorted(os.listdir(lib)):
        if not fn.lower().endswith(".mp4"):
            continue
        vid_id = "lib_" + concept + "_" + fn
        if vid_id in downloaded_ids:
            continue
        try:
            shutil.copy(os.path.join(lib, fn), dst_path)
            downloaded_ids.add(vid_id)
            print(f"[visuals] Used local library clip: {concept}/{fn}")
            return True
        except Exception:
            continue
    return False

def _load_used():
    if not os.path.exists(CACHE_FILE):
        return set()
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
            raise ValueError("used clip registry must be a JSON string list")
        return set(payload)
    except Exception as exc:
        raise RuntimeError(
            f"used clip registry is unreadable; refusing to risk footage reuse: {exc}"
        ) from exc


def _save_used(used):
    temp_path = CACHE_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(sorted(used)[-10000:], f)
        os.replace(temp_path, CACHE_FILE)
    except Exception as exc:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise RuntimeError(
            f"could not persist used clip registry; refusing to complete footage selection: {exc}"
        ) from exc

def _search_pexels(api_key: str, query: str):
    if "pexels" in _RATE_LIMITED:
        return []
    try:
        r = requests.get(SEARCH_URL, headers={"Authorization": api_key},
                         params={"query": query, "orientation": "portrait", "per_page": 15},
                         timeout=30)
    except Exception:
        return []
    if r.status_code == 429:
        _RATE_LIMITED.add("pexels")
        print("[visuals] Pexels rate limit reached - backing off it for the rest of this run")
        return []
    try:
        r.raise_for_status()
    except Exception:
        return []
    out = []
    for v in r.json().get("videos", []):
        user = v.get("user") or {}
        out.append({
            "provider": "pexels",
            "id": "px_" + str(v["id"]),
            "provider_id": str(v["id"]),
            "source_url": v.get("url", ""),
            "creator": user.get("name", ""),
            "creator_url": user.get("url", ""),
            "license": "Pexels License",
            "duration_seconds": float(v.get("duration") or 0),
            "video_files": v.get("video_files", []),
        })
    return out

def _search_pixabay(api_key: str, query: str):
    if "pixabay" in _RATE_LIMITED:
        return []
    try:
        r = requests.get(PIXABAY_VIDEO_URL,
                         params={"key": api_key, "q": query, "per_page": 20,
                                 "safesearch": "true", "video_type": "film"},
                         timeout=30)
    except Exception:
        return []
    if r.status_code == 429:
        _RATE_LIMITED.add("pixabay")
        print("[visuals] Pixabay rate limit reached - using Pexels only for the rest of this run")
        return []
    try:
        r.raise_for_status()
    except Exception:
        return []
    out = []
    for v in r.json().get("hits", []):
        vids = v.get("videos", {}) or {}
        files = []
        for variant in ("large", "medium", "small", "tiny"):
            f = vids.get(variant)
            if f and f.get("url") and f.get("height"):
                files.append({"link": f["url"], "width": f.get("width", 0),
                              "height": f.get("height", 0)})
        if not files:
            continue
        slug = (v.get("tags", "") or "").lower().replace(",", " ")
        out.append({
            "provider": "pixabay",
            "id": "pb_" + str(v["id"]),
            "provider_id": str(v["id"]),
            "source_url": v.get("pageURL", ""),
            "creator": v.get("user", ""),
            "creator_url": "https://pixabay.com/users/" + str(v.get("user", "")) + "-" + str(v.get("user_id", "")) + "/",
            "license": "Pixabay Content License",
            "duration_seconds": float((v.get("videos") or {}).get("large", {}).get("duration") or 0),
            "slug": slug,
            "video_files": files,
        })
    return out

def _search_all(keys: dict, query: str):
    clips = []
    if keys.get("pexels"):
        clips += _search_pexels(keys["pexels"], query)
    if keys.get("pixabay"):
        clips += _search_pixabay(keys["pixabay"], query)
    # Preserve provider relevance order for reproducible candidate review.
    return clips

def _download(video: dict, out_path: str) -> bool:
    """Download the highest useful stock file and retain its source dimensions/URL."""
    files = [
        f for f in video.get("video_files", [])
        if f.get("link") and max(int(f.get("height", 0)), int(f.get("width", 0))) >= 1280
    ]
    if not files:
        return False
    files.sort(key=lambda f: (
        int(f.get("width", 0)) * int(f.get("height", 0)),
        max(int(f.get("width", 0)), int(f.get("height", 0))),
    ), reverse=True)
    selected = files[0]
    try:
        response = requests.get(selected["link"], timeout=120)
        response.raise_for_status()
        if len(response.content) < 20_000:
            return False
        with open(out_path, "wb") as fh:
            fh.write(response.content)
    except Exception:
        return False
    video["selected_file"] = {
        "url": selected.get("link", ""),
        "width": int(selected.get("width", 0)),
        "height": int(selected.get("height", 0)),
        "quality": selected.get("quality", ""),
        "file_type": selected.get("file_type", "video/mp4"),
    }
    return True

def _refine_query(q: str) -> str:
    q_lower = q.lower()

    # SPORT DISAMBIGUATION (legacy safety net): Hidden Logic is an everyday-systems/psychology
    # channel, so football keywords almost never appear. But for the occasional sports-psychology
    # topic (team colours, crowd behaviour), US-indexed stock libraries (Pexels/Pixabay) return
    # AMERICAN football for the word "football", so rewrite clearly-soccer terms to what the
    # libraries actually index. Inert for normal psychology keywords.
    _soccer_terms = {
        "football match": "soccer match",
        "football stadium": "soccer stadium",
        "football pitch": "soccer field",
        "football field": "soccer field",
        "football player": "soccer player",
        "football goal": "soccer goal",
        "football fans": "soccer fans crowd",
        "football crowd": "soccer stadium crowd",
        "world cup": "soccer world cup stadium",
        "penalty kick": "soccer penalty kick",
        "goalkeeper": "soccer goalkeeper",
        "free kick": "soccer free kick",
        "corner kick": "soccer corner kick",
        "home kit": "soccer jersey",
        "football jersey": "soccer jersey",
        "football boots": "soccer cleats",
    }
    for term, repl in _soccer_terms.items():
        if term in q_lower:
            # don't rewrite if it's explicitly American football
            if "american" in q_lower or "nfl" in q_lower or "helmet" in q_lower:
                break
            print(f"[visuals] Sport-disambiguated '{q}' -> '{repl}' (soccer, not NFL)")
            return repl
    # bare "football" -> soccer for this channel (unless explicitly American)
    if "football" in q_lower and not any(w in q_lower for w in ("american", "nfl", "helmet", "quarterback")):
        repl = q_lower.replace("football", "soccer")
        print(f"[visuals] Sport-disambiguated '{q}' -> '{repl}' (soccer, not NFL)")
        return repl

    # Pocket and phone vibration normalization
    mappings = {
        "jeans pocket close up": "person using smartphone",
        "hand reaching into pocket": "checking phone",
        "phone vibrating in pocket": "smartphone",
        "phantom phone vibration syndrome": "checking phone",
        "jeans pocket vibrating": "person using smartphone",
        "jeans pocket": "person using smartphone"
    }
    for old, new in mappings.items():
        if old in q_lower:
            print(f"[visuals] Refined query '{q}' -> '{new}'")
            return new

    # Avoid keyboard/typing/generic button traps for snooze/alarm
    if any(w in q_lower for w in ["snooze", "alarm", "sleep", "wake", "bed"]):
        if any(w in q_lower for w in ["hand hitting", "hitting", "button", "slapping", "slap", "slam", "slamming"]):
            refined = "turning off alarm clock"
            print(f"[visuals] Refined query '{q}' -> '{refined}'")
            return refined
        if "snooze" in q_lower:
            refined = "alarm clock"
            print(f"[visuals] Refined query '{q}' -> '{refined}'")
            return refined
    return q

def _extract_slug(url: str) -> str:
    """Extract descriptive slug from Pexels video URL."""
    if not url:
        return ""
    parts = url.rstrip("/").split("/")
    if parts:
        slug = parts[-1]
        import re
        slug = re.sub(r"-\d+$", "", slug)
        return slug.replace("-", " ")
    return ""

def _get_description(vid: dict) -> str:
    """Retrieve text description for the candidate clip."""
    if vid.get("provider") == "pexels":
        return _extract_slug(vid.get("url", ""))
    return vid.get("slug", "")

def _score_candidates(gemini_key: str, query: str, candidates: list[dict],
                      visual_thesis: str, first_frame_description: str,
                      topic: str, is_first_frame: bool, anchor: str = "") -> dict[str, float]:
    """Score candidates using Gemini. Returns a dict of vid_id -> score (0.0 to 10.0)."""
    if not gemini_key or not candidates:
        return {c["id"]: 0.0 for c in candidates}

    cache_key = (
        topic,
        query,
        visual_thesis,
        first_frame_description,
        is_first_frame,
        anchor,
    )
    if cache_key in _SCORE_CACHE:
        print(f"[visuals] Score cache hit for query: '{query}'")
        cached_scores = _SCORE_CACHE[cache_key]
        return {c["id"]: cached_scores.get(c["id"], 0.0) for c in candidates}

    candidate_items = []
    for c in candidates:
        desc = _get_description(c)
        candidate_items.append(f"- ID: {c['id']} | Description: {desc}")
    candidates_str = "\n".join(candidate_items)

    anchor_line = ""
    if anchor:
        anchor_line = ("\nSCENE ANCHOR (CRITICAL for consistency): every clip in this video must show "
                       f"{anchor}. Give a score of 0 to ANY clip that shows a different subject, vehicle, "
                       "or setting than the anchor (even if it looks nice) - the video must never drift to "
                       "an inconsistent scene.")

    prompt = f"""You are a video editor scoring footage for a YouTube Short.
The Short is about: "{topic}"
The visual thesis is: "{visual_thesis}"
The first frame description is: "{first_frame_description}"

We have a list of candidate video clips from stock search results.
Please score each candidate from 0 to 10 on:
1. Relevance to the visual thesis and topic.
2. Immediate visual clarity (can a viewer understand what is happening in <0.5 seconds?).
3. Not being generic, boring, or irrelevant (e.g. random abstract patterns, nature shots, or disconnected footage).

For the first frame (is_first_frame={is_first_frame}), the footage MUST instantly and visually communicate the topic without needing audio or text.
{anchor_line}
Candidates:
{candidates_str}

Respond ONLY with a JSON object in this format:
{{
  "rankings": [
    {{
      "id": "candidate_id",
      "score": 8.5,
      "reason": "explanation"
    }}
  ]
}}"""

    import scriptgen
    try:
        print("[VISUAL DEBUG] Gemini call")
        res = scriptgen._call(gemini_key, prompt, temperature=0.3)
        rankings = res.get("rankings", [])
        scores = {}
        for item in rankings:
            scores[item.get("id")] = float(item.get("score", 0.0))
        for c in candidates:
            if c["id"] not in scores:
                scores[c["id"]] = 0.0
        _SCORE_CACHE[cache_key] = scores
        return scores
    except Exception as e:
        print(f"[visuals] Candidate scoring failed: {e}; rejecting unreviewed candidates")
        return {c["id"]: 0.0 for c in candidates}

def _search_and_score(keys: dict, gemini_api_key: str | None, query: str,
                      visual_thesis: str, first_frame_description: str,
                      topic: str, is_first_frame: bool, threshold: float,
                      skip_scoring: bool = False, anchor: str = "") -> tuple[list[dict], list[dict]]:
    """Search candidates across providers and score them. Returns (filtered_candidates, all_candidates_sorted)."""
    vids = _search_all(keys, query)
    if not vids:
        return [], []
    vids = vids[:12]  # Limit to top 12 candidates to save API call size and speed up ranking!
    if gemini_api_key and not skip_scoring:
        scores = _score_candidates(gemini_api_key, query, vids,
                                  visual_thesis, first_frame_description,
                                  topic, is_first_frame, anchor=anchor)
        for vid in vids:
            vid["score"] = scores.get(vid["id"], 0.0)
        vids.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        filtered = [v for v in vids if v.get("score", 0.0) >= threshold]
        return filtered, vids
    else:
        # Unscored candidates are never treated as relevant; callers must obtain actual review.
        for vid in vids:
            vid["score"] = 0.0
        return [], vids

STORY_BEAT_LABELS = (
    "observation",
    "action_start",
    "detail",
    "change_comparison",
    "payoff",
)
MIN_VISUAL_SCORE = 8.0
MAX_CANDIDATES_PER_BEAT = 5


class FootageGateError(RuntimeError):
    """Raised when a five-beat, source-reviewed stock sequence cannot be built."""


def _probe_duration(path: str) -> float:
    import subprocess
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True, timeout=30,
    )
    duration = float(probe.stdout.strip())
    if duration <= 0:
        raise ValueError("stock clip has no positive duration")
    return duration


def _sha256(path: str) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sample_clip_windows(path: str, duration: float, segment_duration: float,
                         review_dir: str, beat_index: int) -> tuple[list[dict], list[float]]:
    """Save two sampled frames for up to three valid source windows for visual inspection."""
    import subprocess
    if duration + 0.05 < segment_duration:
        raise ValueError(
            f"clip is {duration:.2f}s but beat needs {segment_duration:.2f}s; looping is disallowed"
        )
    max_start = max(0.0, duration - segment_duration)
    raw_starts = [0.0, max_start / 2.0, max_start]
    starts = []
    for value in raw_starts:
        value = round(max(0.0, min(max_start, value)), 3)
        if not starts or value > starts[-1] + 0.05:
            starts.append(value)
    os.makedirs(review_dir, exist_ok=True)
    samples = []
    for window_index, source_start in enumerate(starts):
        times = [
            min(duration - 0.05, source_start + segment_duration * 0.22),
            min(duration - 0.05, source_start + segment_duration * 0.78),
        ]
        frame_paths = []
        for frame_index, sample_time in enumerate(times):
            frame_path = os.path.join(
                review_dir, f"beat_{beat_index+1}_window_{window_index}_{frame_index}.jpg"
            )
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{sample_time:.3f}", "-i", path,
                 "-frames:v", "1", "-vf", "scale=768:1365:force_original_aspect_ratio=decrease",
                 "-q:v", "4", frame_path],
                capture_output=True, check=True, timeout=45,
            )
            if not os.path.exists(frame_path) or os.path.getsize(frame_path) < 1_000:
                raise RuntimeError("ffmpeg did not produce a usable sampled frame")
            frame_paths.append(frame_path)
        samples.append({"window_index": window_index, "source_start": source_start,
                        "sample_times": times, "frame_paths": frame_paths})
    return samples, starts


def _review_sampled_frames(api_key: str, query: str, beat: str, sentence: str,
                           segment_duration: float, samples: list[dict], topic: str) -> tuple[dict, str]:
    """Ask Gemini vision to inspect actual frames, not only provider titles/tags."""
    import base64
    import scriptgen

    prompt = f"""You are reviewing sampled stock-video frames for a factual Hidden Logic short.
Episode topic: {topic}
Story beat: {beat}
Exact spoken sentence for this beat: {sentence}
Scene-specific stock query: {query}
Required uninterrupted segment duration: {segment_duration:.2f} seconds

Inspect every frame as evidence of what the clip visibly contains. Choose one complete sampled
source window and a crop that keeps the relevant person/object/action inside a 9:16 vertical frame.
Do not infer motion that the sampled frames do not support. Reject unrelated footage, decorative
b-roll, absent action, the wrong place/object/category, or frames where the useful subject cannot
survive a vertical crop. A static close-up can count as action only if a visible hand/object
interaction or a clearly changing detail is present.

Return ONLY JSON. `recommended_window` must be one of the listed window_index values;
`crop_x` must be left, center, or right; `crop_y` must be top, center, or bottom.
{{"relevant":true,"category_match":true,"action_visible":true,"score":8.5,
"visible_action":"...","reason":"...","recommended_window":0,"crop_x":"center","crop_y":"center"}}"""
    parts = [{"text": prompt}]
    for sample in samples:
        for frame_index, frame_path in enumerate(sample["frame_paths"]):
            sample_time = sample["sample_times"][frame_index]
            parts.append({"text": (
                f"Sample window {sample['window_index']} frame {frame_index} at "
                f"{sample_time:.2f} seconds:"
            )})
            with open(frame_path, "rb") as fh:
                parts.append({"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(fh.read()).decode("ascii"),
                }})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    model_names = ["gemini-3.8-flash", "gemini-2.5-flash"]
    try:
        discovered = scriptgen._best_models(api_key)
        model_names = list(dict.fromkeys((discovered or [])[:2] + model_names))
    except Exception:
        pass
    last_error = None
    for model in model_names[:4]:
        try:
            response = requests.post(
                scriptgen.GEMINI_URL.format(model=model),
                headers={"x-goog-api-key": api_key}, json=body, timeout=90,
            )
            response.raise_for_status()
            candidates = response.json().get("candidates", [])
            if not candidates:
                raise ValueError("Gemini visual review returned no candidate")
            text = "\n".join(
                part.get("text", "") for part in candidates[0].get("content", {}).get("parts", [])
                if part.get("text")
            ).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(text)
            if not isinstance(result, dict):
                raise ValueError("visual review must be a JSON object")
            return result, model
        except Exception as exc:
            last_error = exc
    raise FootageGateError(f"sampled-frame review unavailable: {last_error}")


def _valid_visual_review(review: dict, sample_count: int) -> tuple[bool, str]:
    required_bools = ("relevant", "category_match", "action_visible")
    if not all(isinstance(review.get(key), bool) for key in required_bools):
        return False, "malformed_visual_review_flags"
    try:
        score = float(review.get("score", 0))
        window = int(review.get("recommended_window", -1))
    except (TypeError, ValueError):
        return False, "malformed_visual_review_score_or_window"
    if window < 0 or window >= sample_count:
        return False, "invalid_reviewed_source_window"
    if score < MIN_VISUAL_SCORE:
        return False, "visual_relevance_below_threshold"
    if not review.get("relevant"):
        return False, "off_topic_stock_clip"
    if not review.get("category_match"):
        return False, "stock_category_mismatch"
    if not review.get("action_visible") or not str(review.get("visible_action", "")).strip():
        return False, "missing_visible_action"
    if review.get("crop_x") not in {"left", "center", "right"}:
        return False, "invalid_reviewed_crop_x"
    if review.get("crop_y") not in {"top", "center", "bottom"}:
        return False, "invalid_reviewed_crop_y"
    return True, ""


def fetch_backgrounds(api_key: str, keywords: list[str], workdir: str, count: int = 5,
                      pixabay_key: str | None = None, gemini_api_key: str | None = None,
                      visual_thesis: str = "", first_frame_description: str = "", topic: str = "",
                      *, segment_durations: list[float] | None = None,
                      sentences: list[str] | None = None,
                      episode_meta: dict | None = None,
                      max_candidates_per_beat: int = MAX_CANDIDATES_PER_BEAT) -> list[str]:
    """Build exactly five distinct, frame-reviewed stock shots; never fill a weak beat.

    The return type remains a list of local clip paths for compatibility with assemble.py.
    The reviewed clip records are added to `episode_meta['footage_shots']` when supplied.
    """
    if not gemini_api_key:
        raise FootageGateError("Gemini key is required for sampled-frame review")
    if not api_key and not pixabay_key:
        raise FootageGateError("Pexels or Pixabay credentials are required for stock footage")
    if count != len(STORY_BEAT_LABELS) or len(keywords or []) != len(STORY_BEAT_LABELS):
        raise FootageGateError("the episode must have exactly five separate shot queries")
    if not segment_durations or len(segment_durations) != len(STORY_BEAT_LABELS):
        raise FootageGateError("five positive narration-aligned segment durations are required")
    if any(not isinstance(value, (int, float)) or value <= 0 for value in segment_durations):
        raise FootageGateError("segment durations must all be positive")
    if sentences and len(sentences) != len(STORY_BEAT_LABELS):
        raise FootageGateError("five spoken sentences are required to review the beat mapping")
    if any(len(str(q).split()) < 3 for q in keywords):
        raise FootageGateError("shot queries must be specific, scene-level phrases")

    os.makedirs(workdir, exist_ok=True)
    keys = {"pexels": api_key, "pixabay": pixabay_key}
    used = _load_used()
    selected_ids: set[str] = set()
    selected_hashes: set[str] = set()
    paths: list[str] = []
    records: list[dict] = []
    sentence_list = list(sentences or [""] * len(STORY_BEAT_LABELS))

    for beat_index, (beat, raw_query, segment_duration) in enumerate(
        zip(STORY_BEAT_LABELS, keywords, segment_durations)
    ):
        query = str(raw_query).strip()
        candidates = _search_all(keys, query)
        if not candidates:
            raise FootageGateError(f"beat {beat_index+1} ({beat}) has no stock results for {query!r}")
        accepted = None
        failures = []
        for candidate_index, candidate in enumerate(candidates[:max_candidates_per_beat]):
            clip_id = str(candidate.get("id", "")).strip()
            if not clip_id or clip_id in used or clip_id in selected_ids:
                failures.append("clip_id_reused")
                continue
            candidate_path = os.path.join(workdir, f".candidate_{beat_index+1}_{candidate_index+1}.mp4")
            review_dir = os.path.join(workdir, "frame_review", f"beat_{beat_index+1}_candidate_{candidate_index+1}")
            try:
                if not _download(candidate, candidate_path):
                    failures.append("stock_download_or_resolution_failed")
                    continue
                duration = _probe_duration(candidate_path)
                supplied_duration = float(candidate.get("duration_seconds") or 0)
                if supplied_duration > 0 and abs(supplied_duration - duration) > max(2.0, duration * 0.15):
                    candidate["provider_duration_seconds"] = supplied_duration
                if duration + 0.05 < float(segment_duration):
                    failures.append("clip_too_short_for_beat")
                    continue
                file_hash = _sha256(candidate_path)
                if "sha256:" + file_hash in used or file_hash in selected_hashes:
                    failures.append("clip_hash_reused")
                    continue
                samples, allowed_starts = _sample_clip_windows(
                    candidate_path, duration, float(segment_duration), review_dir, beat_index
                )
                review, reviewer_model = _review_sampled_frames(
                    gemini_api_key, query, beat, sentence_list[beat_index],
                    float(segment_duration), samples, topic,
                )
                valid, rejection = _valid_visual_review(review, len(samples))
                if not valid:
                    failures.append(rejection)
                    continue
                recommended_window = int(review["recommended_window"])
                source_start = float(allowed_starts[recommended_window])
                crop_position = {"x": review["crop_x"], "y": review["crop_y"]}
                final_path = os.path.join(workdir, f"bg_{beat_index+1}.mp4")
                os.replace(candidate_path, final_path)
                accepted = {
                    "beat": beat,
                    "query": query,
                    "provider": candidate.get("provider", ""),
                    "provider_id": candidate.get("provider_id", clip_id),
                    "clip_id": clip_id,
                    "source_url": candidate.get("source_url", ""),
                    "download_url": (candidate.get("selected_file") or {}).get("url", ""),
                    "license": candidate.get("license", ""),
                    "creator": candidate.get("creator", ""),
                    "creator_url": candidate.get("creator_url", ""),
                    "duration_seconds": round(duration, 3),
                    "segment_duration_seconds": round(float(segment_duration), 3),
                    "source_start": round(source_start, 3),
                    "crop_position": crop_position,
                    "sha256": file_hash,
                    "local_path": final_path,
                    "sampled_frames": [
                        {"path": os.path.relpath(frame, workdir).replace("\\", "/"),
                         "time_seconds": round(t, 3), "window_index": sample["window_index"]}
                        for sample in samples
                        for frame, t in zip(sample["frame_paths"], sample["sample_times"])
                    ],
                    "review": {
                        "status": "accepted",
                        "reviewer": "Gemini multimodal frame review",
                        "reviewer_model": reviewer_model,
                        "score": float(review["score"]),
                        "relevant": review["relevant"],
                        "category_match": review["category_match"],
                        "action_visible": review["action_visible"],
                        "visible_action": str(review.get("visible_action", ""))[:300],
                        "reason": str(review.get("reason", ""))[:600],
                        "reviewed_window": recommended_window,
                        "reviewed_source_start": round(source_start, 3),
                        "human_review": "pending",
                    },
                }
                paths.append(final_path)
                records.append(accepted)
                selected_ids.add(clip_id)
                selected_hashes.add(file_hash)
                # Keep sampled frames only for the accepted candidate, for human review.
                for other_index in range(candidate_index):
                    previous_dir = os.path.join(
                        workdir, "frame_review", f"beat_{beat_index+1}_candidate_{other_index+1}"
                    )
                    if os.path.isdir(previous_dir):
                        import shutil
                        shutil.rmtree(previous_dir, ignore_errors=True)
                break
            except FootageGateError:
                raise
            except Exception as exc:
                failures.append(type(exc).__name__ + ": " + str(exc)[:160])
            finally:
                if os.path.exists(candidate_path):
                    try:
                        os.remove(candidate_path)
                    except OSError:
                        pass
        if accepted is None:
            if episode_meta is not None:
                episode_meta["footage_shots"] = records
            raise FootageGateError(
                f"beat {beat_index+1} ({beat}) rejected; no reviewed distinct stock clip for "
                f"{query!r}; reasons={','.join(failures[-8:]) or 'no_acceptable_candidates'}"
            )

    # Enforce final episode-level uniqueness before reserving IDs and hashes.
    if len(paths) != 5 or len(set(selected_ids)) != 5 or len(set(selected_hashes)) != 5:
        raise FootageGateError("five-beat footage failed episode-level uniqueness")
    used.update(selected_ids)
    used.update("sha256:" + value for value in selected_hashes)
    _save_used(used)
    if episode_meta is not None:
        episode_meta["footage_shots"] = records
        episode_meta["visual_review_status"] = "automated frame review passed; human review pending"
    return paths

PHOTO_URL = "https://api.pexels.com/v1/search"
THUMB_QUERIES = [
    "cinematic lighting", "abstract geometry", "neon lights dark",
    "blueprint architecture", "macrophotography", "mysterious shadow"
]

def fetch_thumbnail_photo(api_key: str, keywords: list, workdir: str) -> str | None:
    if "pexels_photo" in _RATE_LIMITED:
        return None
    import random as _rnd
    tries = [k for k in keywords if k] + THUMB_QUERIES
    _rnd.shuffle(THUMB_QUERIES)
    for q in tries:
        try:
            r = requests.get(PHOTO_URL, headers={"Authorization": api_key},
                             params={"query": q, "orientation": "portrait",
                                     "per_page": 10, "size": "large"}, timeout=30)
            if r.status_code == 429:
                _RATE_LIMITED.add("pexels_photo")
                return None
            if r.status_code != 200:
                continue
            photos = r.json().get("photos", [])
            _rnd.shuffle(photos)
            for p in photos:
                src = (p.get("src", {}) or {})
                url = src.get("portrait") or src.get("large") or src.get("original")
                if not url:
                    continue
                out = os.path.join(workdir, "thumb_bg.jpg")
                img = requests.get(url, timeout=30)
                if img.status_code == 200 and len(img.content) > 5000:
                    with open(out, "wb") as f:
                        f.write(img.content)
                    return out
        except Exception:
            continue
    return None
