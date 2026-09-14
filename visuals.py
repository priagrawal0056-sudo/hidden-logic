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
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def _save_used(used):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(sorted(used)[-600:], f)
    except Exception:
        pass

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
        out.append({
            "provider": "pexels",
            "id": "px_" + str(v["id"]),
            "url": v.get("url", ""),
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
            "url": "",
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
    random.shuffle(clips)
    return clips

def _download(video: dict, out_path: str) -> bool:
    files = [f for f in video["video_files"] if f["height"] >= f["width"] and f["height"] >= 1280]
    if not files:
        files = [f for f in video["video_files"] if f["height"] >= f["width"] and f["height"] >= 1080]
    if not files:
        return False
    files.sort(key=lambda f: (abs(f["height"] - 1920), -f["height"]))
    try:
        data = requests.get(files[0]["link"], timeout=120)
        data.raise_for_status()
    except Exception:
        return False
    with open(out_path, "wb") as fh:
        fh.write(data.content)
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
        print("[visuals] Candidate scoring unavailable; footage remains unverified.")
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
        for vid in vids:
            vid["score"] = 10.0
        return vids, vids

def fetch_backgrounds(api_key: str, keywords: list[str], workdir: str, count: int = 4,
                      pixabay_key: str | None = None, gemini_api_key: str | None = None,
                      visual_thesis: str = "", first_frame_description: str = "", topic: str = "") -> list[str]:
    keys = {"pexels": api_key, "pixabay": pixabay_key}
    # Lock the whole video to ONE scene concept so clips never drift to a different subject
    # (the car -> motorcycle problem). anchor is fed to the scorer to reject off-anchor clips.
    concept = _detect_concept(topic, keywords, visual_thesis)
    anchor = SCENE_LIBRARY.get(concept, {}).get("anchor", "") if concept else ""
    if concept:
        print(f"[visuals] Scene concept: '{concept}' | anchor lock: {anchor}")
    used = _load_used()
    downloaded_ids: set = set()
    paths: list = []

    if not keywords:
        keywords = ["cinematic documentary", "abstract logic", "modern design"]
        
    queries = []
    for i in range(count):
        queries.append(keywords[i % len(keywords)])

    first_frame_deferred = False   # set True only if slot 0 finds no on-topic clip
    for idx, q in enumerate(queries):
        is_first_frame = (idx == 0)
        threshold = 8.0 if is_first_frame else 7.0
        cleaned_q = _refine_query(q)
        
        # Search and score candidates
        vids, all_vids = _search_and_score(keys, gemini_api_key, cleaned_q,
                                           visual_thesis, first_frame_description,
                                           topic, is_first_frame, threshold, anchor=anchor)
        found = False
        
        # Pass 1: Strict mode - avoid clips used in past videos AND avoid clips already used in THIS video
        for vid in vids:
            vid_id = str(vid["id"])
            if vid_id in downloaded_ids or vid_id in used:
                continue
            out = os.path.join(workdir, f"bg_{len(paths)+1}.mp4")
            if _download(vid, out):
                used.add(vid_id)
                downloaded_ids.add(vid_id)
                paths.append(out)
                found = True
                break
                
        # Pass 2: Relaxed mode - if no fresh clip found for this keyword, allow past clips
        if not found:
            for vid in vids:
                vid_id = str(vid["id"])
                if vid_id in downloaded_ids:
                    continue
                out = os.path.join(workdir, f"bg_{len(paths)+1}.mp4")
                if _download(vid, out):
                    downloaded_ids.add(vid_id)
                    paths.append(out)
                    found = True
                    break

        # Pass 3: Simplified search query (first 2 words) if query is multi-word
        if not found:
            words = q.split()
            if len(words) > 1:
                simple_q = " ".join(words[:2])
                print(f"[visuals] No clips for '{q}'. Trying simplified query '{simple_q}'...")
                svids, sall_vids = _search_and_score(keys, gemini_api_key, simple_q,
                                                     visual_thesis, first_frame_description,
                                                     topic, is_first_frame, threshold,
                                                     skip_scoring=True)
                for vid in svids:
                    vid_id = str(vid["id"])
                    if vid_id in downloaded_ids:
                        continue
                    out = os.path.join(workdir, f"bg_{len(paths)+1}.mp4")
                    if _download(vid, out):
                        downloaded_ids.add(vid_id)
                        paths.append(out)
                        found = True
                        break
                if not found:
                    all_vids.extend(sall_vids)

        # Pass 4: Niche-specific or generic fallback keywords search.
        # IMPORTANT: for the FIRST FRAME we skip the *generic* fallbacks entirely. The first
        # frame is the swipe-or-stay moment - opening on a generic "moody dark / cinematic
        # shadow" clip (or anything off-topic) is exactly what makes viewers swipe in the first
        # second. We'd rather defer the first frame and reuse a later on-topic clip (handled in
        # the deferral below) than open on a mismatched generic shot. Niche fallbacks that are
        # clearly topic-relevant (airport terminal, supermarket aisle, etc.) are still allowed
        # for the first frame; only the generic catch-alls are withheld.
        if not found:
            generic_fallbacks = ["moody dark", "cinematic shadow", "abstract geometry", "mysterious lighting"]
            # Anchor-consistent, proof-oriented fallbacks from the scene library: keeps the whole
            # video on ONE subject and biased toward shots that DEMONSTRATE the mechanism, instead
            # of the old thin "traffic cars"-style fallback that let a car video drift to a bike.
            niche_fallbacks = list(SCENE_LIBRARY.get(concept, {}).get("queries", []))
            # First frame: on-anchor library fallbacks only (never a generic dark shot).
            fallbacks = niche_fallbacks if is_first_frame else (niche_fallbacks + generic_fallbacks)

            for fq in fallbacks:
                print(f"[visuals] No clips for '{q}'. Trying fallback query '{fq}'...")
                fvids, fall_vids = _search_and_score(keys, gemini_api_key, fq,
                                                     visual_thesis, first_frame_description,
                                                     topic, is_first_frame, threshold,
                                                     skip_scoring=True, anchor=anchor)
                for vid in fvids:
                    vid_id = str(vid["id"])
                    if vid_id in downloaded_ids:
                        continue
                    out = os.path.join(workdir, f"bg_{len(paths)+1}.mp4")
                    if _download(vid, out):
                        downloaded_ids.add(vid_id)
                        paths.append(out)
                        found = True
                        break
                if found:
                    break
                else:
                    all_vids.extend(fall_vids)

        # Pass 4.5: Relaxed Score Pass - if we couldn't find any candidate satisfying the threshold,
        # try the highest scored candidate we collected from all search query passes.
        if not found and all_vids:
            all_vids.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            print(f"[visuals] No clips met threshold {threshold} for '{q}'. Trying relaxed score fallback...")
            for vid in all_vids:
                vid_id = str(vid["id"])
                if vid_id in downloaded_ids:
                    continue
                out = os.path.join(workdir, f"bg_{len(paths)+1}.mp4")
                if _download(vid, out):
                    downloaded_ids.add(vid_id)
                    paths.append(out)
                    found = True
                    print(f"[visuals] Downloaded relaxed score fallback: {vid_id} (score: {vid.get('score')})")
                    break

        # Pass 4.7: hand-picked LOCAL proof-clip library (always on-anchor) - use this before we
        # resort to deferring or duplicating, so weak niches can be permanently fixed by the operator.
        if not found and concept:
            out = os.path.join(workdir, f"bg_{len(paths)+1}.mp4")
            if _library_clip(concept, downloaded_ids, out):
                paths.append(out)
                found = True

        # Pass 5: Last resort - duplicate previous downloaded clip to preserve segment pacing.
        # For the FIRST frame there is no previous clip, and we refuse to open on a generic one.
        # Instead we DEFER it: leave the slot empty for now, finish gathering the other (on-topic)
        # clips, then promote the best-scoring on-topic clip to be the opener. This guarantees the
        # swipe-or-stay first frame is always topic-relevant, never a generic dark shot.
        if not found and is_first_frame:
            first_frame_deferred = True
            print(f"[visuals] First frame found no on-topic clip for '{q}'. Deferring - will open "
                  f"with the best on-topic clip from the rest of the video instead of a generic shot.")
        elif not found and paths:
            # duplicate a RANDOM earlier clip, never the immediately-previous one - adjacent
            # identical clips read as "the video is looping". With 2+ clips available we
            # exclude the last; the reuse-offset in assemble then shows a different time
            # window of whichever clip we copy, so the repeat is nearly invisible.
            import random as _dup_rnd
            _pool = paths[:-1] if len(paths) >= 2 else paths
            prev_clip = _dup_rnd.choice(_pool)
            # Reference the SAME file (no copy): assemble keys its reuse-offset counter by
            # path, so a repeated path gets a staggered start time instead of replaying the
            # identical opening seconds (the 'same clip twice in a row' complaint).
            paths.append(prev_clip)
            found = True
            print(f"[visuals] Failed all search queries for '{q}'. Reusing an earlier clip (assemble offsets it).")
        
        if not (_RATE_LIMITED and "pexels" in _RATE_LIMITED and "pixabay" in _RATE_LIMITED):
            time.sleep(0.25)

    _save_used(used)

    # If the first frame was deferred (no on-topic clip found for slot 0), promote the strongest
    # on-topic clip we DID find to the front, so the video opens on-topic. Fall back to just using
    # what we have if we somehow got nothing else.
    if first_frame_deferred and len(paths) >= 1:
        # paths currently holds clips for slots 1..N (the first slot was skipped). Duplicate the
        # first available on-topic clip to serve as the opener too, so pacing/segment count holds.
        # Same-path reference (no copy) so assemble's per-path reuse offset applies here too.
        paths.insert(0, paths[0])
        print("[visuals] Promoted best on-topic clip to the first frame (deferred opener).")
    
    if not paths:
        if _RATE_LIMITED:
            raise RuntimeError("Could not get clips: source(s) rate-limited "
                               f"({', '.join(sorted(_RATE_LIMITED))}). Try again later.")
        raise RuntimeError("Could not download any background clips from Pexels/Pixabay")
        
    if len(paths) < count:
        print(f"[visuals] WARNING: only {len(paths)} distinct clips for {count} segments "
              f"(sources thin or rate-limited); video will use fewer, longer cuts")
              
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
