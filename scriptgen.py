"""
scriptgen.py - v2
Generates a Short script via the free Gemini API, with:
  - a FORMAT x SEED content matrix (expandable seed pool) + idea bank + live trend seeds
  - a second-pass fact check that verifies/corrects every claim
  - structured output: script, title, description, hashtags,
    b-roll keywords (for relevant backgrounds) and emphasis words (for captions)
Free key: https://aistudio.google.com/apikey
"""
import json
import os
import random
import requests
import winner_memory

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite"]  # static fallback
LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200"
_discovered = None


def _best_models(api_key: str) -> list:
    """Ask Google which models this key can actually use, then order for resilience:
    premium Flash first (best quality for scripts/review), then Flash-Lite models
    which have FAR higher daily limits (e.g. 500 RPD vs 20 RPD) as deep fallback so
    the pipeline almost never runs dry. Falls back to the static list if discovery
    fails. Cached per run."""
    global _discovered
    if _discovered:
        return _discovered
    try:
        r = requests.get(LIST_URL.format(key=api_key), timeout=30)
        r.raise_for_status()
        names = []
        for m in r.json().get("models", []):
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            n = m["name"].removeprefix("models/")
            # keep flash + flash-lite text models; drop image/audio/tts/live/experimental
            if "flash" in n and not any(x in n for x in ("image", "audio", "live", "tts", "exp", "8b")):
                names.append(n)
        def version(n):
            import re as _re
            m2 = _re.search(r"gemini-(\d+(?:\.\d+)?)", n)
            return float(m2.group(1)) if m2 else 0.0
        # premium flash first (newest version), THEN lite (newest first). Lite sorts
        # after non-lite at any version, but is always retained as fallback.
        names.sort(key=lambda n: ("lite" in n, -version(n), len(n)))
        # keep more models than before so the high-RPD lite tiers are always reachable
        if names:
            _discovered = names[:15]
            print(f"[scriptgen] model chain (premium first, lite fallback): {_discovered}")
            return _discovered
    except Exception:
        pass
    _discovered = MODELS
    return _discovered

# ---------------------------------------------------------------- content matrix
# Variant A = factual everyday mysteries
FACT_FORMATS = [
    "Why {seed} happens to you constantly",
    "Why you can never escape {seed}",
    "Why {seed} is a universal experience",
    "Why everyone is secretly annoyed by {seed}",
]

# Variant B = opinionated / highly debated / manipulative systems (better retention)
HOTTAKE_FORMATS = [
    ("manipulation", "Why {seed} is definitely not an accident"),
    ("design", "Why {seed} keeps happening no matter what"),
    ("psychology", "The psychological reason behind {seed}"),
    ("behavior", "Why {seed} makes everyone act predictably"),
]

_PILLAR_WEIGHTS = {"manipulation": 40, "design": 30, "psychology": 20, "behavior": 10}


MEMORY_SEEDS = [
    "forgetting why you entered a room", "remembering embarrassing moments forever",
    "names being so easy to forget", "not being able to remember most dreams",
    "forgetting a word right in the middle of a sentence", "remembering song lyrics but not facts",
    "forgetting what someone just told you", "recognizing a face but not the name",
    "forgetting where you put your keys", "remembering childhood smells perfectly"
]

ATTENTION_SEEDS = [
    "feeling your phone vibrate when it didn't", "songs getting stuck in your head",
    "waking up before your alarm", "hearing your name across a noisy room",
    "losing focus the second you sit down to work", "noticing a clock only when it stops",
    "zoning out while driving a familiar route", "re-reading the same line over and over"
]

PERCEPTION_SEEDS = [
    "suddenly seeing the same car everywhere", "time feeling faster as you age",
    "food tasting better when someone else makes it", "a week dragging but a year flying by",
    "the second hand seeming to freeze when you look", "your own voice sounding wrong on recordings",
    "a room feeling smaller in the dark"
]

SOCIAL_BEHAVIOR_SEEDS = [
    "everyone picking the wrong queue", "awkward silences feeling longer", "people copying accents",
    "hating slow walkers", "people interrupting each other", "everyone facing forward in elevators",
    "lowering your voice in a library", "strangers matching your walking speed",
    "mirroring how the person across from you sits", "nobody wanting to sit in the middle seat"
]

COGNITIVE_BIAS_SEEDS = [
    "everyone thinking they are above average", "trusting confident people more",
    "believing the first price you see", "remembering bad reviews more than good ones",
    "assuming expensive means better", "blaming traffic but never your own driving"
]

TECHNOLOGY_SEEDS = [
    "phone notifications being red", "apps begging for a review at the perfect moment",
    "loading bars that clearly lie", "the download stuck at 99 percent",
    "autoplay starting before you decide", "passwords needing a symbol you forget"
]

INTERNET_BEHAVIOR_SEEDS = [
    "clicking on clickbait", "online arguments feeling endless", "scrolling past what you came to read",
    "cookie pop-ups on every site", "the unsubscribe button hiding from you",
    "free trials that demand a card upfront", "infinite feeds you can't put down"
]

DECISION_MAKING_SEEDS = [
    "buying things you don't need", "buying more than you planned", "always picking the medium size",
    "choosing the second-cheapest wine", "adding one more item for free shipping",
    "freezing when there are too many options"
]

HABITS_SEEDS = [
    "checking your phone without thinking", "rewatching the same comfort shows",
    "taking the exact same seat every time", "reaching for your phone the instant you're bored",
    "snacking when you're not even hungry", "opening the fridge for no reason"
]

EMOTIONS_SEEDS = [
    "loving winning arguments", "laughing when you're nervous", "road rage hitting instantly",
    "tearing up at ads you don't care about", "getting angrier the slower the line moves",
    "feeling better the moment you complain"
]

MONEY_PSYCHOLOGY_SEEDS = [
    "free shipping working on you", "everything ending in .99", "'limited time' making you buy now",
    "giant menus costing you more", "the tip screen flipping around to face you",
    "a sale making you spend more, not less", "'buy one get one' that you didn't need"
]

# Physical-space design tricks - the channel's strongest, most visual niche (see AGENTS.md):
# everyday places engineered to steer your behavior.
ENVIRONMENT_SEEDS = [
    "traffic jams appearing out of nowhere", "airport gates changing at the last minute",
    "grocery stores rearranging the shelves", "milk being at the very back of the store",
    "hotel hallways feeling endless", "restaurant menus being enormous",
    "self-checkout always needing the attendant", "IKEA forcing you down one long path",
    "casinos having no clocks or windows", "shopping carts getting bigger every decade",
    "the checkout line you pick always being slowest", "escalators placed far from the entrance",
    "theme park queues that never seem to end", "gas station pumps being painfully slow",
    "elevator doors closing the moment you run"
]

SEEDS = (MEMORY_SEEDS + ATTENTION_SEEDS + PERCEPTION_SEEDS + SOCIAL_BEHAVIOR_SEEDS +
         COGNITIVE_BIAS_SEEDS + TECHNOLOGY_SEEDS + INTERNET_BEHAVIOR_SEEDS + DECISION_MAKING_SEEDS +
         HABITS_SEEDS + EMOTIONS_SEEDS + MONEY_PSYCHOLOGY_SEEDS + ENVIRONMENT_SEEDS)

USED_FILE = "used_topics.json"

def _load_used():
    if os.path.exists(USED_FILE):
        with open(USED_FILE) as f:
            return json.load(f)
    return []

_STORY_MARKERS = ("manipulate", "trick", "dark truth", "secretly", "controls", "behavior", "psychology", "never noticed")
LAST_TOPIC_RETRO = False


TREND_WINDOW = "now 1-d"   # set from config 'trend_window'
LAST_SEED_TREND = 0.0      # heat of the chosen seed, read by the gate bonus


def _pick_seed_by_trend(seeds: list) -> str:
    """Sample candidates and favor whoever is hot right now (non-fatal)."""
    global LAST_SEED_TREND
    sample = random.sample(seeds, min(8, len(seeds)))
    try:
        import trends
        heat = trends.scores([trends.search_term(s) for s in sample], TREND_WINDOW)
        weights = [heat.get(__import__("trends").search_term(s), 0.0) + 5.0 for s in sample]
        chosen = random.choices(sample, weights=weights, k=1)[0]
        LAST_SEED_TREND = heat.get(__import__("trends").search_term(chosen), 0.0)
        hot = max(sample, key=lambda s: heat.get(__import__("trends").search_term(s), 0))
        if LAST_SEED_TREND > 30:
            print(f"[trends] picked '{chosen}' (heat {LAST_SEED_TREND:.0f}/100, "
                  f"hottest in sample: '{hot}')")
        return chosen
    except Exception:
        LAST_SEED_TREND = 0.0
        return random.choice(sample)


def _get_trending_seeds() -> list:
    """Fetch currently-hot general subjects as seeds (cached, non-fatal). Returns [] on
    any failure so the static seed pool is used unchanged."""
    try:
        import trend_seeds
        return trend_seeds.trending_seeds(max_seeds=12)
    except Exception:
        return []

TOPIC_FILTER_PROMPT = """You are a master YouTube retention strategist.
Your job is to pick the SINGLE best video concept from the list below for a cinematic "everyday mysteries explained" Shorts channel.

RULES FOR A WINNING TOPIC:
We score topics out of 10 based on this EXACT weighted formula:
Final Score = (Environment Score * 0.25) + (Annoyance Score * 0.30) + (Universality Score * 0.20) + (Visual Score * 0.10) + (Winner Similarity Score * 0.15)

1. ENVIRONMENT SCORE (0-10): How concrete is the physical environment, everyday setting, or situational context? (e.g. airport, hotel, supermarket, elevator, traffic, gas station, mall, restaurant, airline, or everyday human brain/social contexts like waiting in line, sitting on a bus, checking your phone, shopping, making decisions = 10; abstract theoretical concepts = 0-3).
2. ANNOYANCE SCORE (0-10): Does this setting or context trigger a universal frustration, daily annoyance, or deep curiosity about a relatable mystery? (e.g. long walks, bad sleep, hidden products, phantom phone vibrations, forgetting names, songs stuck in head, urgent sales pressure = 10).
3. UNIVERSALITY SCORE (0-10): Have millions of people personally experienced this exact behavior, quirk, or frustration?
4. VISUAL SCORE (0-10): Can the setting and hook be instantly recognized visually in under one second?

5. WINNER SIMILARITY SCORE (0-10): Evaluate how closely this concept aligns with the traits of our channel's proven winners (which succeed due to relatable situational context, not exact physical locations). Evaluate overlap in context, daily habit, frustration, and reveal against our recent winners.
   Ideal traits to look for:
   - Relatable situational context (e.g. traveling, shopping, driving, using apps, socializing, memory quirks).
   - Universal annoyance or daily frustration/quirk (e.g. waiting, phantom notifications, forgetting names, sales pressure, fixed layouts).
   - High recognition (millions of people have personally experienced it).
   - Visually situational (viewer can picture the physical moment instantly).
   
   To score high (8-10): The concept must embody ALL of these traits (e.g. "Why You Forget Why You Entered A Room" = 9, because it is an everyday situation that directly causes a highly relatable memory frustration).
   To score low (0-4): The concept is merely an academic fact check, abstract trivia, or does not involve a direct everyday annoyance/visual situation (e.g. "Why Airport Security Bins Are Always Gray" = 3, "Why Traffic Signs Use Helvetica" = 2).

6. WINNER CLONE PENALTY: 
   - If Winner Similarity Score > 8: subtract 2 points from final score.
   - If Winner Similarity Score > 9: DO NOT select this candidate. We want ADJACENT winners, not identical clones.

7. CLUSTER STRENGTH SCORE: Evaluate the candidate's environment against the cluster_strengths provided below. A strong cluster means higher baseline views.

8. CLUSTER PENALTY: Subtract 1.5 from the final score if the candidate's environment matches any of these recently used clusters: {recent_clusters}. Exceptional topics can overcome this penalty.

9. TRENDING BOOST: Any candidate prefixed with "TRENDING NOW:" is tied to a live cultural moment (a race weekend, a tournament, etc.) and rides extra real-time search/interest. Add +2 to its final score IF it still embodies a universal everyday-psychology angle (it should - these are pre-filtered to be about relatable perception/behavior, never gossip or results). Do NOT pick a trending candidate that is merely topical but lacks a relatable hidden mechanism. When a trending candidate is genuinely strong, prefer it - capturing live attention is valuable.

CRITICAL GATING RULE:
Prioritize highly relatable everyday mysteries, social behaviors, and brain quirks. Reject any academic or abstract topics.

CHANNEL IDENTITY (narrow on purpose): This channel is "the hidden psychology and design behind everyday life" - the everyday things people see, touch, buy, and feel every day, and the deliberate design or mental trick behind them. STRONGLY prefer topics in: consumer psychology, pricing/sales tricks, store/restaurant/app design, product design, memory and perception quirks, social behavior. DOWNRANK pure science trivia, history facts, abstract physics, or "interesting fact" topics with no everyday hook and no hidden incentive - those dilute the brand identity. The ONLY exception is a genuinely live seasonal sports/event angle (see TRENDING BOOST), which is allowed when tied to universal psychology.

HIDDEN INCENTIVE PREFERENCE (emotional payoff): The most satisfying topics expose a HIDDEN INCENTIVE - someone profits, or you're being nudged to do something - or a deliberate manipulation/design trick. These produce a strong "I've been tricked / that's kind of evil" reaction. DOWNRANK topics whose real explanation is only a dry regulation, building code, or neutral technical requirement (e.g. "U-shaped toilet seats = health code"): they are true but emotionally flat and tend to underperform. If a topic's only payoff is a regulation, score it low unless there is a surprising incentive angle.

HIDDEN MECHANISM PREFERENCE:
Prefer topics where the viewer's current mental model is WRONG. The strongest Hidden Logic topics create a "wait, that's not how I thought it worked" reaction. Reject topics that are merely interesting facts without a hidden mechanism behind them.
  Strong: "Airports make more money from shopping than flying" (viewer assumes airports make money from flights)
  Strong: "Printer companies lose money selling printers" (viewer assumes printers are profitable)
  Weak: "Why airports are expensive" (no wrong assumption challenged)
  Weak: "Why printers cost so little" (interesting fact but no hidden system revealed)

Pick the ONE candidate that scores highest using the formula.

Recent Videos (DO NOT REPEAT THESE CONCEPTS):
{recent_videos}

FLOPPED ANGLES (these badly underperformed - AVOID picking anything close to these):
{flopped_angles}

Cluster Strengths (0-10):
{cluster_strengths}

Candidates:
{candidates}

Evaluate the candidates. Focus purely on physical settings and universal everyday annoyances.
Respond ONLY with JSON: {{"winning_index": 0, "reason": "...", "scores": {{"environment": 0, "annoyance": 0, "universality": 0, "visual": 0, "winner_similarity": 0}}}} (where winning_index is the chosen index from the list above, and scores are the scores of the winning candidate)."""

def _seed_concept(seed: str) -> str:
    s = seed.lower()
    if any(m in s for m in ["grocery", "supermarket", "bakeries", "dairy", "milk", "eggs", "shopping cart", "ikea", "store"]):
        return "supermarket"
    if any(m in s for m in ["airport", "boarding", "security line", "duty-free", "gate"]):
        return "airport"
    if "casino" in s:
        return "mall"
    if "hotel" in s:
        return "hotel"
    if "elevator" in s:
        return "elevator"
    if any(m in s for m in ["traffic", "lane", "red light", "merge", "merging"]):
        return "traffic"
    if any(m in s for m in ["phone", "app", "netflix", "website", "notification"]):
        return "digital"
    if any(m in s for m in ["alarm", "waking", "snooze"]):
        return "sleep"
    if any(m in s for m in ["forget", "memory", "name", "face"]):
        return "memory"
    if any(m in s for m in ["menu", "restaurant", "food", "vending", "drive through"]):
        return "restaurant"
    return s

def seeds_match(seed: str, title_or_topic: str) -> bool:
    import re
    _SEED_STOPWORDS = {"why", "how", "the", "always", "you", "your", "secretly", "annoyed", "happens", "constantly", "universal", "experience", "everyone", "can", "never", "escape", "manipulation", "design", "psychology", "behavior", "manipulate", "trick", "dark", "truth", "controls", "never", "noticed", "a", "an", "of", "who", "that", "in", "at", "to", "from", "for", "and", "with", "his", "her", "their", "nobody", "ever", "one", "being", "been", "was", "were", "is", "are", "about", "places", "place", "thing", "things", "way", "ways", "behind", "concept", "layout", "layouts", "using", "getting", "feeling", "having", "moving", "walking", "going", "doing", "making", "people", "some", "someone", "something", "want", "wanted", "wants"}
    CATEGORY_WORDS = {"airport", "airports", "hotel", "hotels", "supermarket", "supermarkets", "grocery", "groceries", "store", "stores", "traffic", "elevator", "elevators", "escalator", "escalators", "gas", "station", "stations", "mall", "malls", "theme", "park", "parks", "restaurant", "restaurants", "airline", "airlines", "flight", "flights", "plane", "planes", "airplane", "airplanes", "casino", "casinos", "theater", "theaters", "cinema", "cinemas", "fast", "food", "menu", "menus"}
    
    def get_sig_stems(text):
        words = re.findall(r"[a-z0-9]+", text.lower())
        stems = set()
        for w in words:
            if w not in _SEED_STOPWORDS and w not in CATEGORY_WORDS and len(w) >= 3:
                stem = w
                if stem.endswith("ing") and len(stem) > 5:
                    stem = stem[:-3]
                elif stem.endswith("ed") and len(stem) > 4:
                    stem = stem[:-2]
                elif stem.endswith("s") and len(stem) > 3:
                    stem = stem[:-1]
                if len(stem) >= 3:
                    stems.add(stem[:4])
        return stems
        
    seed_stems = get_sig_stems(seed)
    text_stems = get_sig_stems(title_or_topic)
    return bool(seed_stems & text_stems)

def get_recent_clusters(channel_index_path="channel_index.json", cooldown_days=3) -> set[str]:
    """Return clusters that have had a video published in the last N days."""
    import datetime as dt
    import os
    import json
    recent = set()
    if os.path.exists(channel_index_path):
        try:
            with open(channel_index_path, encoding="utf-8") as f:
                idx = json.load(f)
            now = dt.date.today()
            for v in idx:
                v_date_str = v.get("date")
                if not v_date_str:
                    continue
                try:
                    v_date = dt.date.fromisoformat(v_date_str)
                    if (now - v_date).days < cooldown_days:
                        cluster = winner_memory.detect_cluster(
                            v.get("title", ""), v.get("topic", ""))
                        if cluster:
                            recent.add(cluster)
                except Exception:
                    pass
        except Exception:
            pass

    # Also scan drafts directory for local drafts currently pending
    drafts_dir = "drafts"
    if os.path.exists(drafts_dir):
        for d in os.listdir(drafts_dir):
            meta_path = os.path.join(drafts_dir, d, "meta.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    title_text = meta.get("title", "")
                    topic_text = meta.get("topic", "")
                    cluster = winner_memory.detect_cluster(title_text, topic_text)
                    if cluster:
                        recent.add(cluster)
                except Exception:
                    pass
    return recent

def get_recent_seeds(channel_index_path="channel_index.json", cooldown_days=14) -> set[str]:
    import os
    import json
    import datetime as dt
    recent_seeds = set()
    if os.path.exists(channel_index_path):
        try:
            with open(channel_index_path, encoding="utf-8") as f:
                idx = json.load(f)
            now = dt.date.today()
            for v in idx:
                v_date_str = v.get("date")
                if not v_date_str:
                    continue
                try:
                    v_date = dt.date.fromisoformat(v_date_str)
                    days_diff = (now - v_date).days
                    if days_diff < cooldown_days:
                        topic_text = v.get("topic", "")
                        title_text = v.get("title", "")
                        for s in SEEDS:
                            if seeds_match(s, topic_text) or seeds_match(s, title_text):
                                  recent_seeds.add(s)
                except Exception:
                    pass
        except Exception as e:
            print(f"[scriptgen] Error loading recent seeds: {e}")

    # Also scan drafts directory for local drafts currently pending
    drafts_dir = "drafts"
    if os.path.exists(drafts_dir):
        for d in os.listdir(drafts_dir):
            meta_path = os.path.join(drafts_dir, d, "meta.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    topic_text = meta.get("topic", "")
                    title_text = meta.get("title", "")
                    for s in SEEDS:
                        if seeds_match(s, topic_text) or seeds_match(s, title_text):
                            recent_seeds.add(s)
                except Exception:
                    pass
    return recent_seeds

def pick_topic(variant: str = "A", publish_at: str | None = None) -> tuple[str, dict]:
    hist = _load_used()
    used = set(hist)
    
    # 1. Load memory, cooldowns & recent seeds
    winner_memory.init_memory()
    try:
        with open(winner_memory.MEMORY_FILE, encoding="utf-8") as f:
            mem = json.load(f)
        channel_avg = mem.get("channel_avg_views", 534.3)
        clusters_info = mem.get("topic_clusters", {})
    except Exception:
        channel_avg = 534.3
        clusters_info = {}
        
    cooldowns = winner_memory.get_cooldown_clusters(publish_at)
    print(f"[scriptgen] Cooldown clusters for {publish_at or 'now'}: {cooldowns}")
    
    recent_seeds = get_recent_seeds()
    if recent_seeds:
        print(f"[scriptgen] 14-day topic cooldown active for: {sorted(list(recent_seeds))}")
        
    # 3-day cluster cooldown: prevent same environment dominating a week
    recent_clusters = get_recent_clusters()
    if recent_clusters:
        print(f"[scriptgen] 3-day cluster cooldown: {sorted(recent_clusters)}")
    cooldowns = list(set(cooldowns) | recent_clusters)
    
    # Determine top performing clusters (not on cooldown)
    available_clusters = [c for c in winner_memory.CLUSTERS if c not in cooldowns]
    # Rank available clusters by BLENDED strength (views + retention), not raw views.
    # This is what makes the dormant retention data actually steer selection: a cluster
    # that gets fewer views but holds attention now outranks a high-view, low-retention one.
    _strengths = winner_memory.get_cluster_strengths()
    sorted_clusters = sorted(available_clusters,
                             key=lambda c: _strengths.get(c, clusters_info.get(c, {}).get("avg_views", 0.0)),
                             reverse=True)
    top_3 = sorted_clusters[:3]
    print(f"[scriptgen] Top available clusters: {top_3}")
    
    # Exploit seeds: seeds belonging to top_3 clusters
    exploit_seeds = []
    for c in top_3:
        exploit_seeds.extend(winner_memory.ADJACENT_SEEDS.get(c, []))
        
    # Explore seeds: seeds from other available clusters, plus general seeds that don't belong to cooldowns
    explore_seeds = []
    other_clusters = [c for c in available_clusters if c not in top_3]
    for c in other_clusters:
        explore_seeds.extend(winner_memory.ADJACENT_SEEDS.get(c, []))
        
    for s in SEEDS:
        c = winner_memory.detect_cluster(s)
        if c and c in cooldowns:
            continue
        if s not in exploit_seeds and s not in explore_seeds:
            explore_seeds.append(s)
            
    if not explore_seeds:
        explore_seeds = [s for s in SEEDS if winner_memory.detect_cluster(s) not in cooldowns]
    if not explore_seeds:
        explore_seeds = SEEDS

    # CLUSTER BAN (config-controlled).
    # Historically this was a hard-coded "bootstrap" ban that blocked the channel's
    # strongest clusters (airport/hotel/mall/etc.) until the index reached 30 uploads,
    # to force early exploration. With 270+ videos that bootstrap is long over, so the
    # ban is now opt-in via config and OFF by default. Two knobs in config.json:
    #   "cluster_ban_enabled": false        -> master switch (default false)
    #   "cluster_ban_bootstrap_count": 30   -> if enabled, only ban while index < this
    #   "banned_clusters": [...]            -> override the default list if you want
    DEFAULT_BAN_LIST = [
        "airport", "hotel", "airline", "mall", "traffic",
        "escalator", "elevator", "gas_station", "restaurant", "supermarket", "retail_layout"
    ]
    banned_clusters = []
    try:
        import os
        import json
        _cfg = {}
        try:
            import config_loader
            _cfg = config_loader.load_config("config.json")
        except Exception:
            if os.path.exists("config.json"):
                with open("config.json", encoding="utf-8") as _f:
                    _cfg = json.load(_f)
        ban_enabled = bool(_cfg.get("cluster_ban_enabled", False))
        ban_list = _cfg.get("banned_clusters") or DEFAULT_BAN_LIST
        bootstrap_n = int(_cfg.get("cluster_ban_bootstrap_count", 30))
        if not ban_enabled:
            print("[scriptgen] Cluster ban disabled (config 'cluster_ban_enabled' is false) - all clusters available.")
        else:
            idx_len = 0
            if os.path.exists("channel_index.json"):
                with open("channel_index.json", encoding="utf-8") as f:
                    idx_len = len(json.load(f))
            if idx_len < bootstrap_n:
                banned_clusters = list(ban_list)
                print(f"[scriptgen] CLUSTER BAN ACTIVE for: {banned_clusters} (uploads: {idx_len}/{bootstrap_n})")
            else:
                print(f"[scriptgen] Cluster ban enabled but bootstrap met (uploads: {idx_len}/{bootstrap_n}) - no clusters banned.")
    except Exception as e:
        # On any error, fail OPEN (no ban) rather than silently blocking best clusters.
        banned_clusters = []
        print(f"[scriptgen] Cluster ban check failed, defaulting to NO ban ({e})")

    banned_words = banned_clusters

    # Filter out seeds belonging to banned clusters
    filtered_seeds = [s for s in SEEDS if winner_memory.detect_cluster(s) not in banned_clusters]
    filtered_exploit = [s for s in exploit_seeds if winner_memory.detect_cluster(s) not in banned_clusters]
    filtered_explore = [s for s in explore_seeds if winner_memory.detect_cluster(s) not in banned_clusters]
        
    # 2. Select formats/templates
    if variant == "B":
        from collections import Counter as _Counter
        pillar_counts = _Counter(p for p, _ in HOTTAKE_FORMATS)
        templates = [t for _, t in HOTTAKE_FORMATS]
        weights = [_PILLAR_WEIGHTS.get(p, 10) / pillar_counts[p] for p, _ in HOTTAKE_FORMATS]
    else:
        templates = FACT_FORMATS
        weights = [3 if any(m in f for m in _STORY_MARKERS) else 1 for f in FACT_FORMATS]
        
    candidates = []
    used_candidate_concepts = set()
    
    # We want 30 candidates: 21 exploit, 9 explore
    for _ in range(500):
        is_exploit = len(candidates) < 21 and filtered_exploit
        if is_exploit:
            seed = random.choice(filtered_exploit)
        else:
            if filtered_explore:
                seed = random.choice(filtered_explore)
            else:
                seed = random.choice(filtered_seeds)
                
        # Enforce unique seeds in the candidate pool
        if seed in used_candidate_concepts:
            continue
            
        # Skip seeds on the recent-topic cooldown (see get_recent_seeds; currently 14 days)
        if seed in recent_seeds:
            continue
            
        # Ensure seed's cluster is not on cooldown
        seed_cluster = winner_memory.detect_cluster(seed)
        if seed_cluster in cooldowns:
            continue
            
        combo = random.choices(templates, weights=weights, k=1)[0].format(seed=seed)
        if any(w in combo.lower() for w in banned_words):
            continue
        if combo not in used:
            candidates.append(combo)
            used_candidate_concepts.add(seed)
            
        if len(candidates) >= 30:
            break
            
    # Enforce minimum candidate diversity of 70% (unique seeds / total candidates)
    diversity_ratio = len(used_candidate_concepts) / max(1, len(candidates))
    if diversity_ratio < 0.70:
        print(f"[scriptgen] Low candidate diversity ({diversity_ratio:.2f}). Relaxing category cooldowns to rebuild pool.")
        candidates = []
        used_candidate_concepts = set()
        
        available_seeds = [s for s in filtered_seeds if s not in recent_seeds]
        if not available_seeds:
            available_seeds = filtered_seeds
            
        for _ in range(500):
            seed = random.choice(available_seeds)
            if seed in used_candidate_concepts:
                continue
                
            combo = random.choices(templates, weights=weights, k=1)[0].format(seed=seed)
            if any(w in combo.lower() for w in banned_words):
                continue
            if combo not in used:
                candidates.append(combo)
                used_candidate_concepts.add(seed)
                
            if len(candidates) >= 30:
                break
                
    if not candidates:
        print("[scriptgen] WARNING: Reverting to fallback seeds.")
        fallback_seeds = [s for s in filtered_seeds]
        if not fallback_seeds:
            fallback_seeds = SEEDS
        for seed in random.sample(fallback_seeds, min(30, len(fallback_seeds))):
            combo = random.choice(templates).format(seed=seed)
            candidates.append(combo)

    # TREND BRIDGE: if something is genuinely live right now (F1 weekend, World Cup window,
    # etc.), inject 1-2 channel-safe psychology-angle seeds tied to it, tagged so the topic
    # filter can prefer them. These are EVERYDAY-PSYCHOLOGY angles, never gossip/results, and
    # they still pass through every quality gate. Capped to honor the ~20% trend content mix.
    # Skipped entirely when a topic is pinned or nothing is hot. Non-fatal.
    trend_candidates = []
    try:
        import trend_bridge
        live = trend_bridge.trending_seeds(max_seeds=2)
        for tseed in live:
            if tseed in recent_seeds or tseed in used_candidate_concepts:
                continue
            combo = "TRENDING NOW: " + tseed
            trend_candidates.append(combo)
            used_candidate_concepts.add(tseed)
        if trend_candidates:
            print(f"[scriptgen] Trend bridge injected {len(trend_candidates)} live seed(s): {trend_candidates}")
            # put trend candidates at the FRONT and trim the tail to keep the pool ~30
            candidates = trend_candidates + candidates
            candidates = candidates[:max(30, len(trend_candidates))]
    except Exception as e:
        print(f"[scriptgen] Trend bridge skipped (non-fatal): {e}")
            
    # 3. Log top cluster stats
    winner_memory.log_winner_stats(print)
    print("")
    
    # 4. Format candidates list (with freshness penalty tags for winner clones)
    cand_text_list = []
    for idx_c, c in enumerate(candidates):
        similar_titles = [t for t in hist[-50:] if seeds_match(c, t)]
        if similar_titles:
            cand_text_list.append(f"[{idx_c}] {c}  \u26a0\ufe0f SIMILAR to recent: {similar_titles[0]}")
        else:
            cand_text_list.append(f"[{idx_c}] {c}")
        
    cand_text = "\n".join(cand_text_list)
    recent_videos = "\n".join(f"- {cv}" for cv in hist[-50:]) if hist else "None"
    recent_clusters_str = ", ".join(sorted(recent_clusters)) if recent_clusters else "None"
    cluster_strengths = winner_memory.get_cluster_strengths()
    cs_str = "\n".join(f"- {k}: {v}/10" for k, v in cluster_strengths.items())
    # Wire in the (previously write-only) loser dataset so the selector actively avoids
    # angles that already flopped, instead of re-proposing them.
    _losers = winner_memory.get_loser_titles(limit=20)
    flopped_str = "\n".join(f"- {t}" for t in _losers) if _losers else "(none recorded yet)"
    prompt = TOPIC_FILTER_PROMPT.format(candidates=cand_text, recent_videos=recent_videos, recent_clusters=recent_clusters_str, cluster_strengths=cs_str, flopped_angles=flopped_str)
    
    best_combo = candidates[0]
    filter_scores = {}
    
    cfg = {}
    try:
        import config_loader
        cfg = config_loader.load_config("config.json")
    except Exception:
        if os.path.exists("config.json"):
            with open("config.json") as f:
                cfg = json.load(f)
    api_key = cfg.get("gemini_api_key", "")
    
    if api_key:
        try:
            res = _call(api_key, prompt, temperature=0.3)
            idx = int(res.get("winning_index", 0))
            if 0 <= idx < len(candidates):
                best_combo = candidates[idx]
            filter_scores = res.get("scores", {})
            print(f"[scriptgen] Topic Filter selected [{idx}] because: {res.get('reason')}")
        except Exception as e:
            print(f"[scriptgen] Topic Filter failed: {e}. Defaulting to first candidate.")
            
    # Ensure all required keys exist in filter_scores. NOTE: the topic-filter prompt returns
    # "winner_similarity" (NOT "winner_cluster"); using the wrong key here left the persisted
    # winner_cluster_score permanently 0 and disarmed the winner-clone gate on filter failure.
    for key in ["environment", "annoyance", "universality", "visual", "winner_similarity"]:
        if key not in filter_scores:
            filter_scores[key] = 0.0
            
    print(f"[scriptgen] candidate_diversity={len(used_candidate_concepts)}/{len(candidates)}")
    try:
        with open("candidate_log.jsonl", "a", encoding="utf-8") as f:
            json.dump({"diversity": f"{len(used_candidate_concepts)}/{len(candidates)}", "winner": best_combo, "candidates": candidates}, f)
            f.write("\n")
    except Exception:
        pass
        
    hist = _load_used()
    hist.append(best_combo)
    with open(USED_FILE, "w") as f:
        json.dump(hist[-1200:], f, indent=2)
        
    return best_combo, filter_scores


# ---------------------------------------------------------------- prompts
# BRAND SIGNATURE SYSTEM: a rotating set of opening phrases that all communicate the same
# "this was deliberately designed / your brain is being played" idea. Spoken in the first
# ~1 second of EVERY video for instant brand recognition, then immediately followed by the
# physical hook. Rotating (rather than one fixed phrase) avoids "banner blindness" for repeat
# viewers while keeping the channel instantly recognizable. "This isn't an accident." is the
# primary/anchor phrase and is weighted to appear most often.
BRAND_SIGNATURES = [
    "This isn't an accident.",          # primary anchor (weighted heavily below)
    "This isn't an accident.",
    "This isn't an accident.",
    "You've been tricked.",
    "Nobody notices this.",
    "Here's what they don't tell you.",
    "This was designed on purpose.",
    "Your brain falls for this every time.",
    "There's a hidden reason for this.",
]


def _pick_signature() -> str:
    import random as _r
    return _r.choice(BRAND_SIGNATURES)


WRITE_PROMPT = """You are the scriptwriter for 'Hidden Logic', a high-end cinematic documentary YouTube Shorts channel 
about everyday psychological mysteries explained. You write in a calm, confident, cinematic documentary style (Think: Vox, Johnny Harris). 
Your tone is "You've probably noticed this before." Not "DID YOU KNOW...".

Write ONE script on this topic: "{topic}"
Ensure the script strictly follows this Series format: {series_format}

Hard rules:
- {length_rule}
- STORYTELLING/NARRATIVE STYLE (CRITICAL): Do NOT write like a dry mini-documentary or college textbook. Do NOT open with general facts. Instead, place the viewer directly in the scene, building immediate relatability and narrative tension.
  Example:
  Instead of: "Your brain is lying to you. Songs get stuck in your head because of a cognitive loop."
  Write: "You walk away from the radio, but that same chorus keeps echoing in your ears. It is looping on repeat, and you can't shut it off. That's because your brain hasn't finished processing the pattern."
- SCRIPT ORDER (CRITICAL): The script must follow this exact progression:
  1. Location (Physical scene)
  2. Frustration (The annoyance)
  3. Reveal (The twist)
  4. Explanation (The 'why')
  Never explain before the viewer understands the location.
- INFORMATION LOOP RULE (CRITICAL): The script must open an unanswered question within the first 3 seconds that is only fully resolved near the END of the video. The viewer stays because a loop was opened and not yet closed. Do NOT dump all facts upfront. Structure: Question → Context → Context → Answer. Good structure: Hook opens mystery → builds context/tension → delayed payoff resolves it at the end.
- The script must be built around a universal human experience. Find everyday annoyances experienced by millions of people. Then explain the hidden reason. DO NOT think: "What's an interesting design concept?" DO NOT sound like a college lecture.
- BAN WORDS: Do NOT use the words "Hidden", "Secret", "Dark Design", "Manipulation", "Simulation", "Matrix", "Brainwashing", "Control", or "Conspiracy" in the script or title.
- UNIVERSAL APPEAL: The hook must be highly visual and instantly recognizable. Start with the human experience, not the system.
- TITLE FORMULAS (Use one): "Why [Everyday Frustration]", "Why You Always [Do Something]". Example S-Tier Titles: "Why Your Brain Thinks Your Phone Vibrated", "Why Awkward Silences Feel So Long", "Why Songs Get Stuck In Your Head", "Why You Forget Why You Entered The Room".
- TITLE MUST BE A BANGER (CRITICAL): The title's ONE job is to make a scroller stop because it names a frustration they personally feel ALL THE TIME. Before finalizing, the title must pass this test: "Would a random person reading this instantly think 'OMG THIS HAPPENS TO ME'?" If not, rewrite it. The frustration must be:
  * UNIVERSAL: millions experience it weekly (not a niche or clever observation).
  * VISCERAL: it names a specific irritating moment, not an abstract category. Bad: "Why Elevators Are Slow". Banger: "Why The Elevator Always Stops On Every Floor But Yours".
  * PERSONAL: centered on "You/Your", making the viewer the subject. Bad: "Why Wi-Fi Drops". Banger: "Why Your Wi-Fi Dies The Second You Need It".
  * RECOGNIZABLE IN UNDER 1 SECOND: the viewer must instantly grasp what the video is about OR feel an instant pull to find out. Plain frustration titles work; so do short intriguing claims that withhold the answer (e.g. "That one red light is personal"). Avoid only titles that need genuine decoding (obscure metaphors).
  Draft 3 title options - at least one plain/visceral AND at least one intrigue/curiosity-gap - then pick the one with the strongest pull, whether that pull is "that's SO me" or "wait, what? I need to know".
- CURIOSITY GAP RULE (CRITICAL): Two title styles BOTH work for this channel - use whichever fits the topic better, and draft options in both styles:
  STYLE A (plain + visceral): names a universal frustration in direct words. Proven winners: "Why You Can Never Sleep At The Airport", "Why You Always Buy Things You Don't Even Need". Use when the frustration itself is the hook.
  STYLE B (intrigue / curiosity-gap): a short, slightly mysterious claim that makes the viewer NEED the answer. Proven winners: "That one red light is personal", "The Evil Reason Walks Are So Long". Use when a plain title would give away the answer - the title should open a loop the video closes.
  The data shows STYLE B titles can hit the HIGHEST retention (one held 68% of viewers) precisely because the title withholds the reveal. So do NOT default to bland descriptive titles. A title like "Why Airport Gates Change Last Minute" explains itself and gives the viewer no reason to watch - rewrite it into either an instantly-felt frustration (Style A) or an intriguing claim that withholds the answer (Style B).
  Keep titles SHORT (ideally under 8 words for Style B). Center the viewer ("you/your") when natural, but a punchy non-"you" intrigue title ("That one red light is personal") is great too. Avoid titles that need real decoding (no obscure metaphors), but a little mystery that resolves in the first 3 seconds is exactly what makes people stay.
- DESCRIPTION FORMULA: Must be written EXACTLY in this format, replacing the brackets with specific, concrete revelations (no generic mystery phrases): "[Hook] [Subject] uses [concrete design choice/layout/psychological mechanism] to [psychological effect]. Subscribe for daily explanations of everyday mysteries." where [Hook] is one of the following rotated hook phrases (randomly select the most appropriate one for the topic):
  - "Your brain is lying to you."
  - "You've probably noticed this before."
  - "Here's something weird."
  - "This happens to almost everyone."
  - "Most people never realize this."
  - "There's a reason this keeps happening."
- VISUAL THESIS: Every script must define a specific "visual_thesis" that visually encapsulates the core subject in the first second (e.g. 'Airport walks too long -> giant airport corridor', 'Milk hidden at back -> dairy aisle').
- B-ROLL TAGS: Produce a sequence of 5-6 cinematic Pexels keywords that show VISUAL PROGRESSION. The very first keyword MUST perfectly match the spoken hook so the viewer instantly understands the premise visually. Example (Hotel): "Hotel door", "Keycard", "Opening door", "Bed reveal", "Bathroom". CRITICAL FIRST FRAME HOOK: The very first keyword in broll_keywords MUST be a highly specific, high-contrast, instantly recognizable visual representing the core subject of the video (e.g. for snooze: "alarm clock close up" or "hand hitting snooze button"; for airport: "airport gate sign" or "boarding pass close up"). Never use generic, unrelated visuals like "person typing on keyboard", "walking down street", or "man looking at phone" as the first frame unless the hook is literally about typing or phones. SPORT KEYWORDS: if the topic is about football/soccer (World Cup, penalties, goalkeepers, kits), write the keyword as "soccer ..." (e.g. "soccer stadium", "soccer penalty kick") NOT "football ..." - stock libraries return American football for the word "football".
- CURIOSITY-GAP HOOK RULE (THE #1 DRIVER OF "STAYED-TO-WATCH" - THIS DECIDES EVERYTHING):
  Viewers swipe in UNDER 1 second. If more than ~40% swipe in the first 1-2s, YouTube STOPS
  recommending the video no matter how good the rest is - so the opening 1-1.5 seconds ARE the
  packaging (like a thumbnail/title). The FIRST sentence must do BOTH of these AT ONCE:
    (1) INSTANT CLARITY: name/show the familiar everyday thing so the viewer knows EXACTLY what
        this is in under a second - zero figuring-out time. The subject is unmistakable from word one.
    (2) OPEN A SPECIFIC CURIOSITY GAP: in the same breath, reveal there's a precise hidden reason
        behind it that contradicts what they assume - so they feel an itch they NEED scratched.
  WHY (information-gap theory, Loewenstein): curiosity PEAKS when someone already KNOWS the thing
  (they live it) but is shown a SPECIFIC, bounded missing piece. So: reference the familiar AND
  expose the exact gap. General mystery ("the world is strange") does nothing; a precise gap about
  a thing they know ("milk is at the BACK - on purpose") is irresistible.
  FRAME AS A LOSS / MANIPULATION where possible (negativity bias - people feel losses ~2x as hard):
  "it's costing you", "you're being steered", "it's on purpose", "not an accident" beat a neutral fact.
  Rules: first sentence <=10 words, concrete, present tense, NO preamble, NO "have you ever", NO
  "your brain", NO signature phrase, NO slow setup that delays the gap.
  STRONG (scene + instant gap - the viewer is hooked AND knows what it is):
  - "Your 'small' soda doesn't fit the cup holder. On purpose."
  - "Milk sits at the very back of every store. Not by accident."
  - "Your cart pulls left every single time. Someone designed that."
  - "Hotel sheets are always white. There's a cold reason."
  WEAK (scene but NO gap, or a gap that's too slow/vague - these STILL get swiped):
  - "You grab a small drink and it floods the cup holder."   (frustration, but no 'why' itch yet)
  - "You walk into a hotel room and set down your bag."        (pure setup, no gap)
  - "Have you ever wondered why..."                            (slow preamble)
  - "Your brain falls for this every time."                   (abstract, no concrete subject)
- MRBEAST RETENTION RULES:
  * 0-3s HOOK (THE MOST IMPORTANT 3 SECONDS - THIS DECIDES EVERYTHING): This is the single most important part of the entire video. 70% of viewers leave here. The hook must be the BEST-crafted sentence in the script. Requirements, ALL mandatory:
    - <=9 words. Shorter is stronger.
    - Open INSIDE a physical moment the viewer has personally lived (physical hook rule). Put them in the scene, mid-action.
    - It must land an INSTANT micro-payoff or pattern-break in the first sentence - either name the exact frustration they feel ("Your 'small' soda doesn't fit the cup holder.") OR drop a reveal that contradicts what they assume ("Airports make more money from shops than flights."). The viewer must feel something (recognition, surprise, or irritation) before the second sentence.
    - NO throat-clearing, NO setup, NO "Have you ever", NO atmosphere. The first word should already be in the scene.
    - The hook and the title must point at the SAME frustration so the first frame confirms the click.
    Draft THREE hooks, score each on "would this stop MY thumb?", and keep only the most visceral one.
  * ESCALATING MYSTERY (CRITICAL - THIS IS THE #1 RETENTION RULE): Do NOT explain early. The answer must keep moving FURTHER AWAY, not closer, through the middle of the video. After the hook, each sentence must open a BIGGER question than the one before, not resolve it. The viewer stays because the mystery deepens. Structure the body as:
    - 3-8s RE-HOOK: Name the exact experience but reject the obvious explanation. ("And it's not because the airport is huge.") This tells the viewer their first guess is wrong, so they MUST keep watching.
    - 8-20s DEEPEN, DON'T RESOLVE: Each line raises the stakes or reframes the mystery. ("Most people think it's random. It isn't." / "A computer already decided this hours ago.") Every sentence should make the viewer think a new "wait, why?"
    - EVERY SENTENCE OPENS A LOOP: No sentence in the body should fully answer the question. End lines on the edge of a reveal, then pull back one more layer. Bad (resolves instantly): "Your laptop battery blocks X-rays." Good (opens a loop): "Security isn't even looking at your laptop. They're looking at what it hides."
  * MULTI-PEAK RETENTION LOOPS: The body must have at least TWO re-openings of curiosity, not one. After the first partial reveal, pivot with a line like "But that's not even the clever part." then deliver a second, bigger reveal. Three peaks beat one. Pattern: partial reveal -> "but here's the real reason" -> bigger reveal -> "and this is the part nobody notices" -> final reveal.
  * DELAYED REVEAL AT 70-90% (MANDATORY): The single biggest, most satisfying reveal must land in the FINAL THIRD of the script (70-90% through), never at 20%. Before that point the viewer should have pieces but not the full picture. If your draft answers the core question in the first half, you have FAILED - rewrite it to push the payoff to the end.
  * REWARD-STAYING ENDING (NOT A HARD STOP): The final 2-3 sentences must deliver a REFRAME that makes the viewer glad they stayed and changes how they'll see the thing forever. Not "...which is why they ask you to remove it." Instead: "So next time TSA asks for your laptop - they're not checking the laptop. They're checking everything it was hiding." Aim for the viewer to feel "I'll never unsee that" / "no way" - NOT a flat "oh." End on the reframe, then stop sharply.
  * EMOTIONAL TARGET: The payoff must trigger a strong reaction - "I've been tricked", "that's kind of evil", "that makes so much sense", "I'll never unsee that". A merely-interesting "oh, okay" is a failure. Expose a HIDDEN INCENTIVE (who profits, what you were nudged to do) wherever possible - those land harder than neutral technical explanations.
  * SEAMLESS LOOP RULE: The final sentence must seamlessly bleed directly into the very first sentence of the hook, so the replay feels perfectly continuous and the viewer doesn't realize it restarted.
- SHOW DON'T TELL: Describe the visual experience. Make it feel like a Netflix documentary meets Apple Design.
- VISUAL PROOF PER CLAIM: Every major claim in the script must have a corresponding visual proof opportunity. For each claim, there must be supporting footage, image, diagram, or chart that can demonstrate it. Avoid claims that cannot be visually demonstrated. If you say "airports earn more from shopping than flights", there must be a visual (airport mall footage, revenue comparison, passenger shopping). Claims without possible visual proof weaken retention.
- No comedy, no goofy influencer tone, no emojis, no hashtags in the script.
- TAXONOMY: Classify the topic using [cluster]/[subcluster] format (e.g. airport/sleep, hotel/pillows, traffic/merging).
- ABRUPT ENDING: Stop sharply on the climax. Do not wind down or say "subscribe".
- RETURN HOOK (CRITICAL FOR SUBSCRIBERS): The reframe ending must make the viewer feel there is a
  SPECIFIC next thing to discover - not a vague "there's more." The strongest version points at the
  SAME category the video is in, so it reads as "this channel has a whole series exposing THIS kind of
  thing, and I want the next one." Through the content itself, never a begging "subscribe" line. Two
  patterns that work:
    1. Category tease: name the broader pattern this belongs to, implying many siblings. E.g. for an
       airport video: "And the boarding gate is just one of the ways the airport quietly steers you."
    2. Open a small adjacent loop: hint at a related everyday thing with its own hidden reason, left
       unanswered. E.g. "The same trick is why your coffee cup has that little hole - but that's a
       different story." This creates a concrete curiosity gap that pulls them to find the next video.
  One short line is enough. It must NOT blunt the abrupt climax - it comes AFTER the main reveal lands,
  as a final beat, and stays tight. The feeling to create: "every ordinary thing has a hidden logic,
  this channel keeps exposing them, and there's a specific next one I want to see."

- SERIES: Assign this video to ONE recurring series so viewers can binge a theme. Choose the single best fit from: "Supermarket Secrets", "Fast Food Tricks", "Airport Logic", "Hotel Secrets", "Brain Glitches", "App & Website Tricks", "Money & Pricing Tricks", "Shopping Psychology", "Everyday Design". If none fit well, use "Everyday Design". Return as "series".
- SEO KEYWORDS: Return "seo_keywords" - 4 to 6 SPECIFIC search phrases a real person would type to find this exact video, broad-to-specific. Use the actual subject, not generic words. Example for a McDonald's drink video: ["why mcdonalds coke tastes better", "mcdonalds coke secret", "fast food soda", "why fountain drinks taste different", "mcdonalds facts"]. NEVER generic filler like "psychology" alone or random numbers. These become the video's search tags.
- first_comment: a natural, brand-fitting question that invites the viewer to reply AND gives you future topic ideas. Use the content itself, never "subscribe for more". Examples: "What's another everyday thing you've always wondered about?", "Comment one thing you think isn't an accident.", "What should I expose next?" Keep it under 220 characters and end on a complete sentence (it is posted as the pinned first comment).
- HASHTAGS (exactly 3): each must be a concrete, searchable SUBJECT or place tied to the video (#supermarket, #airports, #pricing, #psychology). NEVER a verb, adverb, or filler word lifted from the title (never #noticing, #wait, #forever, #always, #buy). Always include #shorts. Lowercase, no spaces.
- TEXT HOOK (the third hook): top creators use a TRIPLE hook - visual + spoken + ON-SCREEN TEXT. Return "text_hook": a 2-5 word punchy on-screen line shown for the first ~2 seconds that AMPLIFIES the curiosity gap and is DIFFERENT from the spoken words (it must add intrigue, not repeat the narration). 80% watch muted, so this text plus the first frame must sell the click. Examples: "This isn't an accident", "On purpose.", "You've been tricked", "Look closer", "It's costing you". Make it specific to the video where possible.
- NET INFORMATION GAIN / THE SWAP TEST (CRITICAL for distribution): YouTube's 2026 algorithm caps videos that just repeat an idea many channels already made (the "conflict radius" - it stalls around 30k views). The script MUST add something genuinely NEW to the common explanation: a specific surprising number, a non-obvious second mechanism, a fresh analogy, or a counterintuitive twist - not the generic version everyone says. SWAP TEST: if this exact script could sit on any other channel and make sense, it's too generic - add the unique angle/detail that makes it unmistakably yours.
- MATCH, THEN EXCEED (MrBeast): the FIRST sentence must immediately confirm the promise of the title (so the viewer who clicked feels "yes, this is what I came for") and then over-deliver. Never open on a tangent or a slow build that delays the payoff the title promised.
- TARGET REACTION: write the script to produce ONE specific shareable reaction by the end ("no way", "I've been tricked", "I'll never unsee that"). People share reactions, not facts - and a one-sentence, easily-retold payoff is what gets sent to a friend.

Respond ONLY with JSON:
{{"script": "...", "title": "...", "description": "...", "taxonomy": "...", "visual_thesis": "...", "series": "...", "text_hook": "...", "seo_keywords": ["..","..","..",".."], "hashtags": ["#shorts","#hiddenlogic","..",".."], "broll_keywords": ["..","..","..","..","..",".."], "emphasis_words": ["..",".."], "first_comment": "..."}}"""

REVIEW_PROMPT = """You are a brutal YouTube Shorts retention analyst who has seen 10,000 viral shorts.

Script:
\"\"\"{script}\"\"\"

{topic_lock_instruction}

TASK 1 - FACTS, THEME & STORYTELLING: Check every claim. Ground the script entirely in a shared human experience and an everyday annoyance. Rewrite the script if it sounds like an explanation or a textbook definition rather than a story. Use storytelling/narrative style to describe a concrete situation rather than dryly stating facts (e.g. use "You've been awake for six hours. The airport is empty. There are twenty seats right in front of you. And somehow you still can't lie down. That's because those armrests..." instead of "Airport seating uses fixed armrests to prevent passengers from lying down. This isn't an accident...").

TASK 1B - TITLE (RECOGNITION FIRST): Optimize the title. BAN colons and category labels. The title's #1 job is INSTANT RECOGNITION: a viewer must recognize the everyday setting/frustration in under one second. This channel's top performers use PLAIN, direct titles, not clever wordplay. Prefer the simple recognizable phrasing over a cleverer one. Good (plain + recognizable): "Why Airports Make You Walk Miles", "Why Your Small Drink Is Actually Too Big", "Why You Forget Why You Entered The Room". Avoid (over-clever / abstract): "The Glitch That Forces Songs To Loop In Your Head", "The Reason Airlines Force You To Stop In Weird Cities". Keep the curiosity coming from the FRUSTRATION itself ("Why You Always..."), not from a riddle the viewer has to decode. Use the "Why [Everyday Frustration]" / "Why You Always [Do Something]" formulas. Center the viewer ("YOU"). A title can be curious AND plain - plain wins ties.

TASK 1C - HOOK IMMEDIACY, ENDING & PACING: The very first sentence (0-3s hook) must be <=10 words and must immediately describe an actual physical, relatable human experience/moment (e.g., "You walk into...", "You grab..."). It must NOT be abstract or slow (e.g., no "Have you ever wondered", "Ever noticed how", "Your brain is being tricked", etc.). If it is abstract/slow, rewrite the hook to be an immediate physical moment. CRITICAL: The first 3 seconds must REVEAL a hidden system, not merely introduce a topic. Bad: "Why airports are so expensive." Good: "Airports make more money from shopping than flying." Ensure the ending is abrupt. Ensure the 50% pattern interrupt exists. Enforce short sentences (<15 words). Ensure the SEAMLESS LOOP perfectly connects the very last line directly into the first line so it loops invisibly. LENGTH (CRITICAL FOR RETENTION): the ENTIRE script must be UNDER ~80 words (~30 seconds). Shorter Shorts retain far better - on this channel a 29s video pulled 3.2x the views of a 48s one. If the script runs long, CUT secondary beats, qualifiers, and any repeated idea until it fits. Keep only: hook, the single biggest reveal, and the loop ending.

TASK 1E - VISUAL PROOF CHECK: Every major claim in the script must have a corresponding visual proof opportunity. For each claim, confirm that supporting footage, images, diagrams, or charts exist that can demonstrate it on screen. Flag any claim that cannot be visually demonstrated — these weaken retention because the viewer sees generic B-roll instead of proof. If a claim lacks visual proof, rewrite it to be visually demonstrable or remove it.

TASK 1D - ESCALATING MYSTERY, DELAYED PAYOFF & ENDING (CRITICAL - REWRITE IF IT FAILS): This is the #1 retention check.
(a) ESCALATION: Through the body, does the mystery DEEPEN rather than resolve? Each sentence should open a bigger question, not answer one. If any body sentence fully resolves the question early (e.g. "Your laptop battery blocks X-rays." stated flatly in the first half), REWRITE it to pull back another layer ("Security isn't even looking at your laptop - they're looking at what it hides.").
(b) DELAYED REVEAL POSITION: The single biggest reveal MUST land in the final third (70-90% through the script). If the core answer arrives in the first half, you MUST restructure so the payoff is at the end: Question -> deepen -> deepen -> partial -> BIGGEST REVEAL last.
(c) MULTI-PEAK LOOPS: Does the body re-open curiosity at least twice (a "but that's not even the clever part" pivot before a second, bigger reveal)? If there's only one peak, add a second curiosity re-opening.
(d) REWARD-STAYING ENDING: Does the script end on a REFRAME that makes staying worth it and makes the viewer go "no way / I'll never unsee that" - NOT a flat stop like "...which is why they ask you to remove it"? If the ending merely stops, rewrite the last 2-3 sentences into a reframe.
Score 'delayed_reveal_score' (0-10): 10 = biggest reveal at the very end with escalation throughout and a reframe ending; 0 = answer dumped upfront, flat ending. Reject anything below 8.

TASK 2 - RETENTION (Topic Scoring System): Score the (corrected) script using this /50 rubric (each category /10, min score for approval is 40/50):
- Relatable (/10): Can the viewer instantly remember experiencing this?
- Memory Trigger (/10): How quickly does the viewer remember a real-life moment?
- Hook Retention (/10): Does the first 3 seconds create an irresistible psychological grip that survives the 70% swipe-away test?
- Surprise (/10): Genuine "wait, what?" moment?
- Shareability (/10): Will someone send this to a friend?
Sum these 5 categories into 'overall' out of 50.

TASK 2B - TITLE GRADER: Score the corrected title out of 30. RECOGNITION is the dominant factor for this channel - a plain title that is instantly recognizable beats a clever one.
- Recognition (/10): Can a viewer recognize the setting/frustration in under one second? Plain, concrete wording scores high; abstract or riddle-like wording scores low. If the title needs decoding, cap this at 5.
- Frustration (/10): Does the title trigger a universal everyday frustration or annoyance?
- Curiosity (/10): Does it spark curiosity about the reason? NOTE: curiosity must come from the relatable frustration, NOT from clever/cryptic wordplay. Penalize titles that sacrifice instant recognition for cleverness (e.g. "The Glitch That..."). When a plain phrasing and a clever phrasing are otherwise equal, the plain one scores higher overall. STRONGEST titles frame the topic as a small mystery or contradiction using PLAIN words - they imply a hidden reason without a riddle. Examples (plain AND intriguing, score high): "Airports Already Knew Your Gate Would Change", "Restaurants Don't Want You Buying Medium", "Websites Literally Forget You Exist". These beat the dry "Why X happens" form when the plainness is preserved.

TASK 3 - TOPIC FIDELITY & VISUAL THESIS: Score how closely the script/title stays within the requested seed topic family: '{seed_topic}'.
- Topic Fidelity (/10): How closely does the script/title stay within the exact requested seed topic family ('{seed_topic}') without drifting to a broader/different category? (10 = perfect match, 0 = completely drifted/swapped to a different subject/family).
- Subject Retention (/10): How consistently is the seed topic discussed throughout the script?
- Visual Thesis Verification: Does the script define a clear, immediate visual thesis? Extract and return this as 'visual_thesis'.

TASK 4 - HOOK TYPE CLASSIFICATION: Classify the hook style into either 'physical_moment' (starts with an immediate physical action/moment like 'You walk into...', 'You grab...', 'You press...') or 'explainer' (starts with an explanation, fact, question, or abstract concept).

TASK 5 - FIRST FRAME SCORE: Score the opening scene's instant visual recognition (0-10):
- Can a viewer identify the PHYSICAL LOCATION in under 0.5 seconds? (airport, store, hotel, car, elevator, etc.)
- Can a viewer understand the SITUATION instantly without any explanation?
- Can a viewer picture themselves there immediately?
Scoring: 0-3 = abstract/requires thought, 4-6 = recognizable after a moment, 7-8 = strong recognition, 9-10 = instant "I've been there". Reject anything below 8.

TASK 5B - SWIPE-STOP / CURIOSITY-GAP SCORE (0-10) - THE SINGLE MOST IMPORTANT RETENTION CHECK:
Score ONLY the first 1-1.5 seconds (the first sentence / first ~6 words), because that is where
50-75% of viewers swipe and where this channel is losing them. Score whether the opening does BOTH
at once: (a) INSTANT CLARITY - the viewer knows EXACTLY what familiar everyday thing this is, with
zero figuring-out time (subject named/shown in the first few words); AND (b) SPECIFIC CURIOSITY GAP
- it immediately exposes a precise, bounded hidden reason that contradicts what they assume ("on
purpose", "not an accident", "it's costing you"), an itch they NEED scratched. Bonus for a loss/
manipulation frame (negativity bias). A pure relatable frustration with NO gap, OR a vague/general
gap, OR any setup that delays the gap past the first sentence, scores LOW. 0-3 = slow/vague/pure
setup, 4-6 = clear but no real gap (or a gap that's too slow), 7-8 = clear + a real gap, 9-10 =
instant clarity + an irresistible specific gap in the first ~1 second. Return as 'swipe_stop_score'.
Reject anything below 8 - if low, REWRITE the first sentence so the subject is unmistakable AND a
specific hidden reason is teased immediately.

TASK 6 - RETENTION PREDICTION: Predict how well this script will retain viewers through the entire Short (0-10). Average these four factors:
- Scene Strength: Is the setting vivid and instantly recognizable?
- Frustration Strength: Does the viewer feel the annoyance viscerally?
- Curiosity Gap: Does the hook create an irresistible "why?" that survives 5+ seconds?
- Reveal Payoff: Does the explanation feel satisfying and surprising?
Score 0-10. Reject anything below 8.

TASK 7 - TOPIC RECOGNITION SCORE (0-10): Can the viewer instantly recognize the topic?
- Can viewer identify location in <0.5 seconds?
- Can viewer understand topic without audio?
- Does first frame immediately match title?
Score 0-10. Reject anything below 8.

TASK 8 - HOOK STRUCTURE & FIRST FRAME: Extract the 'hook_structure' (e.g., 'Action -> Frustration') and write a 'first_frame_description' depicting the visual opening. Extract 'taxonomy' in [cluster]/[subcluster] format.

TASK 9 - PREDICTED VIEWS SCORE (0-10): Predict the absolute performance based on cluster strength, hook performance, topic novelty, retention prediction, and first frame quality. Rank 0-10.

TASK 10 - VIEWER IDENTITY SCORE (0-10): Evaluate how effectively this topic builds audience loyalty (0-10). Average these four factors:
- Uniquely Hidden Logic (/2.5): Does it fit the brand theme of exposing everyday psychological mysteries?
- Memorable (/2.5): Is the everyday realization unforgettable?
- Discussion Generating (/2.5): Is it debate-worthy or prompts viewers to comment/debate?
- Emotionally Relatable (/2.5): Does it trigger a strong, universal relatable emotion/frustration?
Score 0-10. Reject anything below 8.

TASK 11 - EMOTIONAL PAYOFF (0-10): Score the gut reaction the ENDING produces. The target is a strong "no way / I've been tricked / that's kind of evil / I'll never unsee that" reaction. A merely-interesting "oh, okay" is a low score.
- Does the payoff expose a HIDDEN INCENTIVE (who profits, what you were manipulated into doing, a deliberate design trick)? Incentive/manipulation reveals score high.
- Pure regulation / building-code / dry technical answers ("it's required by health codes") are CORRECT but emotionally flat - score these 4 or below UNLESS the script reframes them into something surprising.
Score 0-10. Reject anything below 7. If below 7 because the explanation is a flat regulation/technical answer, note in 'fix' that the topic may simply lack an emotionally satisfying hidden incentive.

TASK 12 - NET INFORMATION GAIN / SWAP TEST (0-10): YouTube's 2026 algorithm caps videos that just repeat an idea many channels already made (the "conflict radius" - it stalls ~30k views). Score how much genuinely NEW value this script adds versus the generic version everyone makes. SWAP TEST: if this exact script could sit on any other channel and still make sense, it is too generic. High score (8-10) = adds a specific surprising number, a non-obvious second mechanism, a fresh analogy, or a counterintuitive twist that makes it unmistakably original. Low score (0-5) = the same explanation anyone could write / a reworded common fact. Return as 'novelty_score'. Reject below 7 - if low, note in 'fix' exactly what NEW angle, number, or mechanism to add.

Respond ONLY with JSON:
{{"issues_found": "facts note or 'none'", "script": "final corrected script", "title": "corrected title", "taxonomy": "cluster/subcluster", "visual_thesis": "...", "hook_structure": "...", "first_frame_description": "...", "relatable": n, "memory_trigger": n, "hook_retention": n, "surprise": n, "shareability": n, "overall": n, "title_recognition": n, "title_frustration": n, "title_curiosity": n, "hook_type": "physical_moment" or "explainer", "topic_fidelity": n, "subject_retention": n, "first_frame_score": n, "swipe_stop_score": n, "novelty_score": n, "retention_prediction": n, "topic_recognition_score": n, "predicted_views_score": n, "viewer_identity_score": n, "delayed_reveal_score": n, "emotional_payoff_score": n, "fix": "one sentence on the biggest weakness"}}"""


PROVIDER = "gemini"  # set from config by run_daily; "gemini" or "claude_code"


def _repair_json_quotes(s: str) -> str:
    """Best-effort repair of JSON whose string VALUES contain unescaped double quotes (a
    common LLM failure, e.g. a reply with scare-quotes: {"reply": "that "legend" is elite"}).
    Walks the string and escapes any double-quote that is inside a value rather than acting
    as a structural delimiter. Conservative: if it can't tell, it leaves the char alone."""
    out = []
    in_str = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
            i += 1
            continue
        # inside a string value
        if c == '\\' and i + 1 < n:        # keep existing escape sequences intact
            out.append(c)
            out.append(s[i + 1])
            i += 2
            continue
        if c == '"':
            # look ahead past whitespace: a structural closing quote is followed by
            # one of  :  ,  }  ]  (or end of string). Anything else = a stray inner quote.
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ':,}]':
                out.append('"')           # structural quote - ends the string
                in_str = False
            else:
                out.append('\\"')          # stray inner quote - escape it
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _call_claude_code(prompt: str, allow_search: bool = False) -> dict:
    """Uses Claude Code headless mode (claude -p), billed to the user's
    Claude subscription. Requires: Claude Code installed and logged in once."""
    import shutil, subprocess
    exe = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not exe:
        raise RuntimeError(
            "claude_code provider selected but Claude Code is not installed. "
            "Install it (see https://docs.claude.com/en/docs/claude-code/overview), "
            "run 'claude' once to log in, or set llm_provider back to 'gemini'."
        )
    last_err = None
    for attempt in range(2):
        try:
            cmd = [exe, "-p", prompt, "--output-format", "json"]
            if allow_search:
                cmd += ["--allowedTools", "WebSearch"]
            else:
                # Single-shot text generation: we want ONE model response, not an agent that
                # loops, loads MCP servers, or reaches for tools. These flags cut the per-call
                # startup overhead (the main reason the CLI fallback is slow) with no effect on
                # output quality. --max-turns 1 stops agentic looping; restricting tools to none
                # skips MCP/tool initialization.
                cmd += ["--max-turns", "1", "--allowedTools", ""]
            proc = subprocess.run(cmd,
                                  capture_output=True, text=True, timeout=300,
                                  encoding="utf-8", errors="replace")
            if proc.returncode != 0 or not proc.stdout:
                raise RuntimeError(f"claude -p failed: {(proc.stderr or '')[-300:]}")
            result = json.loads(proc.stdout).get("result", "")
            result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            if not result.startswith("{"):
                # tolerate prose around the JSON: take outermost braces
                i, j = result.find("{"), result.rfind("}")
                if i == -1 or j == -1:
                    raise ValueError("no JSON object in claude output")
                result = result[i:j + 1]
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                # the model's text value often contains unescaped inner quotes (e.g. a
                # reply with scare-quotes), which breaks strict JSON. Repair by escaping
                # stray quotes inside string values, then retry; if that still fails, hand
                # back the raw string so the caller can salvage the text rather than lose it.
                repaired = _repair_json_quotes(result)
                try:
                    return json.loads(repaired)
                except Exception:
                    return {"_raw": result}
        except Exception as e:
            last_err = e
    raise RuntimeError(f"claude -p failed after retry: {last_err}")


_dead_models = set()

# lightweight signals the orchestrator reads for the attention digest
RUN_EVENTS = {"used_claude_fallback": False, "gate_fallbacks": 0, "all_gemini_down": 0, "gemini_exhausted": False, "waited_for_perminute": False}

# ANTI-SAMENESS ROTATION (research: YouTube's 2026 "mass-production" filter suppresses
# channels where every video has the same length, structure, and pacing - topic variety
# alone is not enough). We rotate the target length AND the structural skeleton per video
# so consecutive uploads don't fingerprint as identical templates. Completion-rate research
# also favors a spread that includes shorter, tighter videos.
import random as _rnd

# HARD word cap. Retention is the whole game: your real data shows a 29s Short pulled 3.2x the
# views of a 48s one (and "watched for longer"). 20-35s is the retention sweet spot; over-length
# is the single biggest retention killer. A script over this cap is rejected and trimmed. At the
# channel's narration pace (~2.6-2.7 words/sec) 82 words lands ~30s.
MAX_SCRIPT_WORDS = 78

_LENGTH_VARIANTS = [
    # Calibrated to THIS channel's real retention data AND 2025/26 Shorts research: the 20-35s
    # band retains best; over-length kills completion. These are HARD caps, not suggestions.
    "44 to 56 words (about 16-21 seconds - this channel's BEST-performing length). Tight and "
    "punchy: one clear hook, one strong beat, one payoff. HARD CAP - if you exceed it, cut "
    "sentences until you're under it. Every word must earn its place.",
    "50 to 64 words (about 19-24 seconds). Punchy, zero filler, room for one escalating beat. "
    "HARD CAP - count your words and trim to fit.",
    "60 to 78 words (about 23-29 seconds). A touch longer for a richer story, but NEVER drag - "
    "only use the extra room if the payoff genuinely needs it. HARD CAP at 78 words.",
]

# Repurposable curiosity-gap hook PATTERNS, distilled from proven scroll-stopping short-form
# openers (information-gap theory + open loops + negativity bias). The writer rotates a few of
# these per video so hooks stay fresh AND always open a specific gap in the first ~1 second.
# This is the "repurpose proven hooks" engine: unlimited fresh hooks from a small set of structures.
CURIOSITY_HOOK_PATTERNS = [
    "IT'S ON PURPOSE - name the familiar thing, then assert it was deliberately designed. ('Milk sits at the back of every store. On purpose.')",
    "WRONG ASSUMPTION - state what everyone believes, then flip it. ('You think the long airport walk is bad planning. It isn't.')",
    "IT'S COSTING YOU - name the thing, reveal it's quietly taking your money or time. ('Your cart got bigger so you'd spend more.')",
    "HIDDEN NUMBER - a specific surprising number about a familiar thing. ('Your \"small\" soda tripled in size since 1960. On purpose.')",
    "SOMEONE DECIDED THIS - reveal an invisible hand behind an everyday annoyance. ('A computer already chose your gate change hours ago.')",
    "YOU'VE NEVER NOTICED - point at a thing they see daily but never questioned. ('Every elevator has a mirror. Not for the reason you think.')",
    "NOT AN ACCIDENT - a frustration reframed as deliberate design. ('Checkout lines feel unfair because they're built that way.')",
    "THE REAL REASON - tease that the obvious explanation is wrong and a better one is coming. ('Hotels use white sheets for a colder reason than clean.')",
    "QUIETLY MANIPULATING YOU - a familiar object/space steering your behavior. ('Slow music in stores is quietly slowing you down.')",
    "ONCE-NORMAL-NOW-WEIRD - a 'wait, that used to be normal?' fact that poses a question. ('We kept these as pets for centuries. Then they vanished - here's why.')",
    "MOST PEOPLE ARE WRONG - state the common belief about a familiar thing, then flip it (contrarian framing reliably out-pulls neutral facts). ('Most people blame bad luck for the slow checkout. It's actually math.')",
    "IT'S AFFECTING YOU RIGHT NOW - a familiar thing quietly steering the viewer in this exact moment. ('Right now, this page's layout is deciding what you'll buy.')",
    "CLIMAX TEASE - open on the most surprising END image, then rewind to explain it (the payoff is teased, not given). ('This empty shelf is why you spent $40 more. Here's how.')",
    "DISBELIEF NUMBER - a number so off it sounds wrong, about a thing they know. ('Supermarkets rearrange ~200 items a year so you never learn the layout.')",
]

_STRUCTURE_VARIANTS = [
    "TEMPLATE A - LISTICLE MYSTERY: (e.g. '5 Secrets You Didn't Know About X'). Rapid montage of facts. Secret #1, Secret #2, leading to a mini-surprise at the end.",
    "TEMPLATE B - QUESTION -> EXPLANATION (Story style): 'Ever wonder why...?'. Quickly setup the scenario. Explain the reveal clearly with bullet points. End with a 'wow' significance statement.",
    "TEMPLATE C - SCENARIO CONFLICT -> SOLUTION: Dramatized problem 'Every morning you...'. Explain the hidden reason that causes it. Give a quick tip/benefit at the end."
]


def _rotate_style() -> tuple[str, str]:
    """Pick a length rule and a structural skeleton for THIS video. Weighted toward the
    channel's proven best length (~17-21s) based on real retention data, with the longer
    options used less often. Returns (length_rule, skeleton)."""
    # weight: 55% the proven sweet spot, 30% slightly longer, 15% longest - bias hard
    # toward what the data shows actually retains on THIS channel.
    length_rule = _rnd.choices(_LENGTH_VARIANTS, weights=[68, 27, 5])[0]
    skeleton = _rnd.choice(_STRUCTURE_VARIANTS)
    return length_rule, skeleton


class _GeminiQuotaExhausted(RuntimeError):
    """Raised when Gemini is persistently rate-limited this call, to trip the Claude
    fallback fast instead of grinding 15s per model across the whole chain.

    is_daily=True means the daily/credit cap is hit (Gemini dead for hours -> latch to
    Claude). is_daily=False means a per-minute throttle (Gemini back in ~60s -> waiting one
    minute and retrying Gemini is far faster than routing the whole run through the slow CLI).
    is_server_busy=True means a Google-side 5xx outage: NOT our quota, no fixed clear-time, so
    don't do the 60s per-minute wait and don't latch Gemini off for the whole run - just use
    Claude for THIS video and let the next video retry Gemini fresh (the outage may have lifted).
    """
    def __init__(self, message, is_daily=False, is_server_busy=False):
        super().__init__(message)
        self.is_daily = is_daily
        self.is_server_busy = is_server_busy


def _call_gemini(api_key: str, prompt: str, temperature: float, allow_search: bool = False) -> dict:
    import time
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    last_err = None
    rate_limit_hits = 0          # how many models rejected us with a per-minute 429 this call
    daily_hits = 0               # how many of those were the DAILY cap (Gemini dead for hours)
    server_busy_hits = 0         # how many models returned 5xx (Google-side outage, NOT our quota)
    RATE_LIMIT_TRIP = 3          # after this many 429s, stop grinding and hand off to Claude fast
    SERVER_BUSY_TRIP = 3         # after this many 5xx, the whole Gemini fleet is busy - bail to Claude
    for model in _best_models(api_key):
        if model in _dead_models:
            continue
        for attempt in range(2):
            try:
                r = requests.post(GEMINI_URL.format(model=model, key=api_key), json=body, timeout=90)
                if r.status_code == 404:
                    _dead_models.add(model)
                    break  # model retired, try next model
                if r.status_code == 429:
                    err_msg = ""
                    try:
                        err_msg = r.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    last_err = RuntimeError(f"429 rate limit from {model}: {err_msg}")
                    is_daily = "day" in err_msg.lower() or "daily" in err_msg.lower()
                    rate_limit_hits += 1
                    if is_daily:
                        daily_hits += 1
                    # FAST FALLBACK: if Gemini is persistently throttled this call, stop the
                    # 15s-per-model grind and raise so _call() decides what to do. We tag whether
                    # it's the DAILY cap (latch to Claude) or just per-minute (wait it out).
                    if rate_limit_hits >= RATE_LIMIT_TRIP:
                        raise _GeminiQuotaExhausted(
                            f"Gemini rate-limited ({rate_limit_hits} models hit 429 this call, "
                            f"{daily_hits} daily). Last: {err_msg[:80]}",
                            is_daily=(daily_hits >= 1),
                        )
                    if is_daily:
                        print(f"[scriptgen] {model} daily limit exceeded. Banning for this run.")
                        _dead_models.add(model)
                        break
                    # per-minute: try the NEXT model right away (no long sleep). Only the very
                    # first hit waits briefly, to let a momentary spike clear.
                    if attempt == 0 and rate_limit_hits == 1:
                        print(f"[scriptgen] {model} rate limited (daily={is_daily}), brief 5s wait...")
                        time.sleep(5)
                        continue
                    print(f"[scriptgen] {model} per-minute limit, moving on immediately.")
                    break  # move on to the next model with no further sleep
                if r.status_code in (500, 502, 503):
                    # 5xx is a Google-SIDE outage (server busy / overloaded), which is DIFFERENT
                    # from 429 (our quota). It is NOT fixed by trying other Gemini models - if the
                    # flash endpoint is throwing 503, the whole fleet is usually overloaded, so
                    # grinding all 12 models just burns ~a minute of 5s waits. Count the hits and,
                    # once it's clearly a fleet outage, trip straight to the Claude fallback.
                    server_busy_hits += 1
                    last_err = RuntimeError(f"{r.status_code} from {model} (Google server busy, not a quota issue)")
                    if server_busy_hits >= SERVER_BUSY_TRIP:
                        raise _GeminiQuotaExhausted(
                            f"Gemini servers busy ({server_busy_hits} models returned 5xx this call). "
                            f"This is a Google-side outage, not your quota - handing off to Claude.",
                            is_server_busy=True,
                        )
                    if attempt == 0:
                        print(f"[scriptgen] {model} returned {r.status_code} (server busy, not quota), retrying once in 5s...")
                        time.sleep(5)
                        continue
                    print(f"[scriptgen] {model} still {r.status_code} (server busy), skipping it for this run")
                    _dead_models.add(model)
                    break
                if r.status_code in (400, 401, 403):
                    raise RuntimeError(
                        f"Gemini rejected the API key ({r.status_code}). Your key looks wrong or revoked. "
                        "Get a fresh one at https://aistudio.google.com/apikey (it should start with AIza) "
                        "and update config.json."
                    )
                r.raise_for_status()
                text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                return json.loads(text)
            except _GeminiQuotaExhausted:
                raise  # bubble straight up to _call so it falls back to Claude fast
            except RuntimeError:
                raise  # fatal key errors: stop immediately with the clear message
            except Exception as e:
                last_err = e
                time.sleep(2)
    hint = ""
    if last_err and "429" in str(last_err):
        hint = (" This looks like the free-tier quota. Per-minute limits clear in ~1 minute; "
                "the daily limit resets at midnight US Pacific time. Your normal daily run uses "
                "only 6-12 calls, so this mainly happens during heavy testing.")
    raise RuntimeError(f"All Gemini models failed after retries. Last error: {last_err}.{hint}")


# provider order: primary first, then the other as automatic fallback.
FALLBACK_ENABLED = False


def _is_quota_error(err: Exception) -> bool:
    if isinstance(err, _GeminiQuotaExhausted):
        return True
    s = str(err).lower()
    return ("429" in s or "rate limit" in s or "quota" in s
            or "persistently rate-limited" in s
            or "per-minute limit" in s
            or "claude -p failed" in s or "resource_exhausted" in s
            or "overloaded" in s
            or "all gemini models failed" in s)


def _claude_cli_available() -> bool:
    """True if the Claude Code CLI is installed and on PATH (Windows-aware)."""
    import shutil
    return bool(shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe"))


def _call(api_key: str, prompt: str, temperature: float, allow_search: bool = False) -> dict:
    """Primary LLM dispatch. Tries Gemini first; if Gemini is out of credits / quota /
    fully unavailable, automatically falls back to the Claude Code CLI (billed to the
    user's Claude subscription, no per-call cost). The switch is per-call and logged
    loudly so a Gemini outage never silently kills a run.

    If PROVIDER is explicitly set to 'claude_code', Claude is used directly with no Gemini
    attempt (unchanged behavior).
    """
    # Explicit Claude-only mode: honor it without touching Gemini.
    if PROVIDER == "claude_code":
        return _call_claude_code(prompt, allow_search=allow_search)

    # Run-level latch: once Gemini has run out this run, don't keep hammering it on every
    # subsequent call (that's what burned ~15 min on rate-limit waits). Go straight to Claude.
    if RUN_EVENTS.get("gemini_exhausted") and _claude_cli_available():
        return _call_claude_code(prompt, allow_search=allow_search)

    try:
        return _call_gemini(api_key, prompt, temperature, allow_search=allow_search)
    except _GeminiQuotaExhausted as e:
        # PER-MINUTE throttle: Gemini is supposed to be back in ~60s, so the FIRST time we hit
        # it we wait one minute and retry on fast Gemini (cheaper than the slow CLI). But if
        # we ALREADY did that wait earlier this run and Gemini is still throttled, waiting
        # again is pointless - the quota is genuinely blown for this run. In that case we latch
        # to Claude just like a daily cap, so we stop rediscovering it's dead on every call.
        if e.is_server_busy:
            # Google-side 5xx outage: don't wait 60s (that's for per-minute quota, not outages)
            # and don't latch Gemini off for the whole run - just use Claude for THIS video and
            # let the next video try Gemini again, since the outage may have already cleared.
            print("[scriptgen] Gemini servers busy (5xx) - using Claude for this video only; "
                  "next video will retry Gemini.")
        elif not e.is_daily and not RUN_EVENTS.get("gemini_exhausted"):
            if not RUN_EVENTS.get("waited_for_perminute"):
                # First per-minute hit this run: do the one-time 60s wait + retry.
                import time
                print("[scriptgen] Gemini per-minute limit hit. Waiting 60s for it to clear "
                      "(faster than routing everything through Claude)...")
                RUN_EVENTS["waited_for_perminute"] = True
                time.sleep(60)
                try:
                    return _call_gemini(api_key, prompt, temperature, allow_search=allow_search)
                except Exception:
                    pass  # the 60s wait didn't help -> Gemini is blown for this run
            # Either the wait just failed, or we already waited earlier this run. Stop trying
            # Gemini for the rest of the run.
            RUN_EVENTS["gemini_exhausted"] = True
        elif e.is_daily:
            RUN_EVENTS["gemini_exhausted"] = True  # daily cap -> dead for hours
        # Fall back to Claude.
        if not _is_quota_error(e):
            raise
        if _claude_cli_available():
            RUN_EVENTS["used_claude_fallback"] = True
            print("=" * 60)
            print("[scriptgen] GEMINI QUOTA EXHAUSTED -> USING CLAUDE FOR THE REST OF THIS RUN")
            print(f"[scriptgen] (reason: {str(e)[:120]})")
            print("=" * 60)
            try:
                return _call_claude_code(prompt, allow_search=allow_search)
            except Exception as ce:
                raise RuntimeError(f"Gemini exhausted AND Claude fallback failed: {ce}") from ce
        raise RuntimeError(
            "Ran out of Gemini quota and no Claude fallback is available. "
            "Install the Claude Code CLI and run 'claude' once to log in "
            "(https://docs.claude.com/en/docs/claude-code/overview)."
        ) from e
    except Exception as e:
        if not _is_quota_error(e):
            raise  # a real error (bad prompt, network, etc.) - don't mask it
        # Gemini is out of credits / rate-limited / all models down. Fall back to Claude.
        if _claude_cli_available():
            RUN_EVENTS["used_claude_fallback"] = True
            RUN_EVENTS["gemini_exhausted"] = True  # latch: stay on Claude for the rest of the run
            print("=" * 60)
            print("[scriptgen] GEMINI OUT OF CREDITS / QUOTA -> FALLING BACK TO CLAUDE CODE CLI")
            print(f"[scriptgen] (reason: {str(e)[:120]})")
            print("=" * 60)
            try:
                return _call_claude_code(prompt, allow_search=allow_search)
            except Exception as ce:
                raise RuntimeError(
                    f"Gemini out of credits AND Claude fallback failed: {ce}"
                ) from ce
        # No Claude CLI installed - tell the user exactly how to enable the fallback.
        raise RuntimeError(
            "Ran out of Gemini credits and no Claude fallback is available. "
            "Install the Claude Code CLI and run 'claude' once to log in so the pipeline "
            "can fall back to your Claude subscription automatically "
            "(https://docs.claude.com/en/docs/claude-code/overview)."
        ) from e


MIN_SCORE = 8       # target score; overridden by 'min_quality' in config.json
MAX_ATTEMPTS = 8    # tries per video before falling back to the best script
QUALITY_FLOOR = 6   # absolute minimum: below this, no video (config 'quality_floor')

REVISE_PROMPT = """You wrote this 'Everyday Mysteries Explained' Shorts script. A retention expert scored it {score}/50 
(relatable {relatable}, memory_trigger {memory_trigger}, hook_retention {hook_retention}, surprise {surprise}, shareability {shareability}) 
and scored the title {title_score}/30 (recognition {title_recognition}, frustration {title_frustration}, curiosity {title_curiosity})
and said the biggest weakness is: "{fix}"

Attack the LOWEST-scoring dimensions above directly.

Script:
\"\"\"{script}\"\"\"

Rewrite it to fix exactly that weakness while keeping everything that works. Same rules: the ENTIRE script must stay UNDER 80 words (~30 seconds) - CUT, never pad, because shorter Shorts retain far better; every sentence <=15 words and one idea each, storytelling hook <=9 words, escalate -> ~50% pattern interrupt -> twist -> payoff -> signature ending loop, written like a premium cinematic documentary (Think: Vox, Johnny Harris). The first sentence MUST begin with an immediate physical, everyday moment.

Respond ONLY with JSON (keep title/description/hashtags/broll_keywords/emphasis_words consistent with the new script):
{{"script": "...", "title": "...", "description": "...", "hashtags": ["#shorts","#hiddenlogic","..",".."], "broll_keywords": ["..","..","..","..","..",".."], "emphasis_words": ["..",".."], "first_comment": "..."}}"""

import random

SERIES_FORMATS = [
    "WHY IT FEELS THAT WAY (e.g. Why Hotel Rooms Feel Familiar, Why Airports Feel So Stressful)",
    "WHY YOU ALWAYS... (e.g. Why You Always Buy More Than Planned, Why You Always Pick The Slowest Line)",
    "DESIGNED TO... (e.g. Designed To Keep You Shopping, Designed To Make You Stay Longer)"
]

def _build_prompt(topic, length_rule, variant):
    series_format = random.choice(SERIES_FORMATS)
    return WRITE_PROMPT.format(topic=topic, length_rule=length_rule, series_format=series_format)

def _extract_seed_topic(topic: str) -> str:
    if not topic:
        return ""
    s = topic.strip()
    if s.startswith("ON-DEMAND video about "):
        s = s[len("ON-DEMAND video about "):]
        idx = s.find(".")
        if idx != -1:
            s = s[:idx]
    
    # Strip a subtitle/suffix ONLY when the colon or dash is a real separator (a colon, or
    # a dash with spaces around it like " - " / " — "). Do NOT split on in-word hyphens
    # such as "Last-Minute" or "Drive-Thru" - that previously mangled "A Last-Minute World
    # Cup Goal" into the seed "a last", which let the reviewer swap the whole subject.
    import re as _re
    # colon: take text before the first colon (handles "Airport Design: The Reason ...")
    if ":" in s:
        s = s.split(":")[0]
    # space-delimited dash separators only
    s = _re.split(r"\s+[-—–]\s+", s)[0]
            
    # Clean the string
    s = s.lower()
    # Remove common qualifiers/fillers AND sentence-framing words, so the seed is the core
    # SUBJECT (e.g. "world cup goal") rather than a whole clause ("a last-minute world cup
    # goal feels better than an early one"). A tight subject makes the fidelity check sharp.
    fillers = {
        "design", "concept", "logic", "mystery", "mysteries", "frustration",
        "frustrations", "why", "how", "the", "always", "system", "systems",
        "a", "an", "you", "your", "feels", "feel", "better", "than", "more",
        "is", "are", "always", "almost", "just", "really", "actually", "even",
        "that", "this", "it", "its", "of", "to", "in", "on", "and", "or",
    }
    words = s.split()
    cleaned_words = [w for w in words if w not in fillers]
    if cleaned_words:
        s = " ".join(cleaned_words)
    return s.strip()

def get_rolling_quality_threshold(default_threshold=46.0) -> float:
    try:
        import os
        import json
        if not os.path.exists("channel_index.json"):
            return default_threshold
        with open("channel_index.json", encoding="utf-8") as f:
            idx = json.load(f)
        scores = [float(v["quality_score"]) for v in idx if "quality_score" in v and v["quality_score"] is not None]
        if not scores:
            return default_threshold
        
        # 1. Rolling 80th percentile of recent 50 uploads
        recent_scores = scores[-50:]
        recent_scores.sort()
        n_recent = len(recent_scores)
        idx_p80 = min(max(0, int(n_recent * 0.8)), n_recent - 1)
        rolling_80 = recent_scores[idx_p80]
        
        # 2. Top 25th percentile (75th percentile from bottom) of all uploads
        all_scores = list(scores)
        all_scores.sort()
        n_all = len(all_scores)
        idx_p75 = min(max(0, int(n_all * 0.75)), n_all - 1)
        top_25 = all_scores[idx_p75]
        
        # Take max and clamp. The ceiling matters a lot for THROUGHPUT: the model reliably
        # produces scripts in the ~43-47 range, so a target pinned at 48 means EVERY video
        # burns all its revision attempts chasing a number it almost never hits, then ships
        # the best one anyway - pure wasted time (worse when on the slow Claude fallback).
        # We keep the bar meaningful (44 floor) but cap it at 46 so a good script clears in
        # 1-2 attempts instead of grinding 5. This is the rolling-target version of the same
        # "don't let the threshold chase your own output" fix from earlier.
        val = max(rolling_80, top_25)
        val = min(max(44.0, val), 46.0)
        return val
    except Exception as e:
        print(f"[scriptgen] Error calculating rolling threshold: {e}")
        return default_threshold

def generate(api_key: str, topic: str | None = None, extra_guidance: str = "",
             rater_benchmark: str = "", variant: str = "A", strict_topic_lock: bool = False,
             publish_at: str | None = None) -> dict:
    rolling_threshold = get_rolling_quality_threshold(default_threshold=46.0)
    print(f"[scriptgen] Dynamic quality threshold (max of rolling 80th and top 25th percentile): {rolling_threshold:.1f}")
    
    # Define local min_score and quality_floor matching the rolling threshold
    # min_score_local is the TARGET the loop aims for and revises toward (the rolling
    # 80th-percentile bar). It is NOT a hard publish floor: a script that clears every
    # categorical quality gate (hook, first_frame, retention, payoff, identity, title)
    # should ship even if its numeric score lands a point or two under the rolling target.
    # The only numeric HARD floor is a fixed absolute backstop from config (absolute_quality_floor),
    # set low enough that it only catches genuinely broken output, never good-but-not-peak
    # scripts. This stops the self-raising rolling bar from starving the channel of videos.
    min_score_local = rolling_threshold
    try:
        import json as _json, os as _os
        _cfg_floor = 40.0
        if _os.path.exists("config.json"):
            with open("config.json", encoding="utf-8") as _f:
                _cfg_floor = float(_json.load(_f).get("absolute_quality_floor", 40.0))
        quality_floor_local = _cfg_floor
    except Exception:
        quality_floor_local = 40.0

    pinned = topic is not None
    filter_scores = {}
    if not pinned:
        topic, filter_scores = pick_topic(variant, publish_at=publish_at)
        if float(filter_scores.get("winner_similarity", 0)) > 9.0:
            raise RuntimeError("QUALITY & GATING REJECTION [winner_clone]: Best candidate is a winner clone (winner_similarity > 9). Sacrificing slot.")
    seed_topic = _extract_seed_topic(topic) if topic else ""
    length_rule, skeleton = _rotate_style()
    best, best_score = None, -1
    accepted_this_attempt = False
    for attempt in range(MAX_ATTEMPTS):
        if not pinned and attempt > 0:
            topic, filter_scores = pick_topic(variant, publish_at=publish_at)
            seed_topic = _extract_seed_topic(topic) if topic else ""
            
        prompt = _build_prompt(topic, length_rule, variant)
        prompt += "\n\n" + skeleton
        if extra_guidance:
            prompt += extra_guidance
        if strict_topic_lock and seed_topic:
            lock_guidance = (
                f"\n\nSTRICT TOPIC LOCK ACTIVE:\n"
                f"You MUST write the script and title strictly about the requested subject family: '{seed_topic}'.\n"
                f"You are strictly forbidden from swapping the subject family to a broader or different concept "
                f"(e.g., if the topic is '{seed_topic}', do not write about general stores, malls, or shopping "
                f"unless '{seed_topic}' is exactly that). The script and title must use the terminology "
                f"and context of '{seed_topic}' (e.g. if the topic is casino, use casino floors, slots, no clocks in casinos)."
            )
            prompt += lock_guidance
        import random as _hr
        _patterns = _hr.sample(CURIOSITY_HOOK_PATTERNS, 4)
        prompt += ("\n\nHOOK PROCESS (CRITICAL - this decides 'stayed-to-watch'): before writing, "
                   "draft THREE distinct opening hooks for this topic, each built on a DIFFERENT one "
                   "of these proven curiosity-gap patterns (repurpose each to THIS exact topic):\n- "
                   + "\n- ".join(_patterns) +
                   "\nApply the CURIOSITY-GAP HOOK RULE and the swipe-stop test to each: do the first "
                   "~6 words instantly name the familiar thing AND open a specific hidden-reason gap? "
                   "Pick the SINGLE strongest, write the script opening with it, and output ONLY the "
                   "winning script (not the alternatives).")
        data = _call(api_key, prompt, temperature=0.95)
        data["topic"] = topic
        data["filter_scores"] = filter_scores
        review = None
        
        lock_inst = (
            f"STRICT TOPIC LOCK ACTIVE:\n"
            f"You MUST verify that the script and title stay strictly focused on the requested subject family: '{seed_topic}'.\n"
            f"If the script has drifted away from '{seed_topic}' (e.g. if the requested topic is '{seed_topic}' but the script is about general stores/shopping), you MUST rewrite the script and title to bring it back to '{seed_topic}' and use its language. Do not allow it to escape the topic family."
            if strict_topic_lock else
            f"TOPIC FIDELITY EVALUATION:\n"
            f"Evaluate how closely the script and title stay within the requested subject family: '{seed_topic}'."
        )
        
        for _r in range(2):
            try:
                review_prompt = REVIEW_PROMPT.format(
                    script=data["script"],
                    topic_lock_instruction=lock_inst,
                    seed_topic=seed_topic
                )
                if rater_benchmark:
                    review_prompt += rater_benchmark
                review = _call(api_key, review_prompt, temperature=0.2, allow_search=False)
                break
            except Exception as e:
                review_err = e
        if review is None:
            raise RuntimeError(f"REVIEW FAILED twice; refusing to publish unverified content. ({review_err})")
        data["script"] = review.get("script", data["script"])
        if review.get("title"):
            data["title"] = review["title"]
        data["factcheck"] = review.get("issues_found", "n/a")
        data["visual_thesis"] = review.get("visual_thesis", "")
        data["taxonomy"] = review.get("taxonomy", "")
        data["hook_structure"] = review.get("hook_structure", "")
        data["first_frame_description"] = review.get("first_frame_description", "")
        data["predicted_views_score"] = float(review.get("predicted_views_score", 0))
        
        score = float(review.get("overall", 0))
        if score >= min_score_local:
            print(
                f"[scriptgen] Attempt cleared target threshold "
                f"(score={score}, threshold={min_score_local}); running full quality gates."
            )
        # Subcluster Penalty (-2 to scores)
        if data.get("taxonomy"):
            recent_taxonomies = set()
            if os.path.exists("channel_index.json"):
                import datetime as dt
                try:
                    with open("channel_index.json", encoding="utf-8") as f:
                        idx = json.load(f)
                    thirty_days_ago = (dt.datetime.now() - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    for entry in idx:
                        if entry.get("date", "") >= thirty_days_ago and entry.get("taxonomy"):
                            recent_taxonomies.add(entry["taxonomy"])
                    if data["taxonomy"] in recent_taxonomies:
                        print(f"[scriptgen] SUBCLUSTER PENALTY: {data['taxonomy']} used recently. -2 to score.")
                        score -= 2.0
                        data["predicted_views_score"] = max(0.0, data["predicted_views_score"] - 2.0)
                except Exception:
                    pass
                    
        topic_fidelity = float(review.get("topic_fidelity", 10.0))
        subject_retention = float(review.get("subject_retention", 10.0))
        
        data["topic_fidelity"] = topic_fidelity
        data["subject_retention"] = subject_retention
        
        data["relatable"] = review.get("relatable", 0)
        data["memory_trigger"] = review.get("memory_trigger", 0)
        data["hook_retention"] = review.get("hook_retention", 0)
        data["surprise"] = review.get("surprise", 0)
        data["shareability"] = review.get("shareability", 0)
        
        # Title Grading Scores
        title_rec = float(review.get("title_recognition", 0))
        title_frust = float(review.get("title_frustration", 0))
        title_cur = float(review.get("title_curiosity", 0))
        title_score = title_rec + title_frust + title_cur
        
        data["title_recognition"] = title_rec
        data["title_frustration"] = title_frust
        data["title_curiosity"] = title_cur
        data["title_score"] = title_score
        data["hook_type"] = review.get("hook_type", "explainer")
        
        # V5 Retention-First scores
        first_frame_score = float(review.get("first_frame_score", 0))
        swipe_stop_score = float(review.get("swipe_stop_score", 0))
        novelty_score = float(review.get("novelty_score", 0))
        retention_prediction = float(review.get("retention_prediction", 0))
        topic_recognition_score = float(review.get("topic_recognition_score", 0))
        viewer_identity_score = float(review.get("viewer_identity_score", 0))
        delayed_reveal_score = float(review.get("delayed_reveal_score", 0))
        emotional_payoff_score = float(review.get("emotional_payoff_score", 0))
        data["first_frame_score"] = first_frame_score
        data["swipe_stop_score"] = swipe_stop_score
        data["novelty_score"] = novelty_score
        data["retention_prediction"] = retention_prediction
        data["topic_recognition_score"] = topic_recognition_score
        data["viewer_identity_score"] = viewer_identity_score
        data["delayed_reveal_score"] = delayed_reveal_score
        data["emotional_payoff_score"] = emotional_payoff_score
        
        # Environment/Annoyance/Universality topic scores
        env_score = float(filter_scores.get("environment", 0))
        ann_score = float(filter_scores.get("annoyance", 0))
        univ_score = float(filter_scores.get("universality", 0))
        
        data["environment_score"] = env_score
        data["annoyance_score"] = ann_score
        data["universality_score"] = univ_score
        data["winner_cluster_score"] = float(filter_scores.get("winner_similarity", 0))
        data["visual_score"] = float(filter_scores.get("visual", 0))
        
        print(f"[scriptgen] Topic fidelity score: {topic_fidelity}/10, Subject retention score: {subject_retention}/10 (seed: '{seed_topic}')")
        if topic_fidelity < 7.0 or subject_retention < 7.0:
            print(f"[scriptgen] WARNING: Low fidelity/retention detected. Seed: '{seed_topic}', Title: '{data.get('title')}'")
            
        data["quality_note"] = review.get("fix", "")
        if score > 0 and LAST_SEED_TREND >= 50:
            bonus = 1.0 if LAST_SEED_TREND >= 80 else 0.5
            print(f"[scriptgen] trend bonus +{bonus} (subject heat {LAST_SEED_TREND:.0f}/100)")
            score += bonus
        data["trend_heat"] = round(LAST_SEED_TREND, 1)
        data["quality_score"] = score
        
        is_fidelity_ok = (not strict_topic_lock) or (topic_fidelity >= 8.0 and subject_retention >= 8.0)
        # When the topic is PINNED (idea bank, --hero trend, on-demand) the topic-filter
        # never runs, so filter_scores is empty and "visual" is 0. The old code therefore
        # made this gate ALWAYS fail for pinned topics, forcing every such video to burn all
        # MAX_ATTEMPTS (~8x the LLM cost) before shipping anyway. Pinned topics are pre-vetted,
        # so they pass the topic gate by definition.
        is_topic_gate_ok = pinned or float(filter_scores.get("visual", 0)) >= 8.0
        is_title_gate_ok = title_score >= 24 and title_frust >= 7.0
        is_hook_physical = data.get("hook_type") == "physical_moment"
        is_first_frame_ok = first_frame_score >= 8.0
        is_swipe_ok = swipe_stop_score >= 7.0   # first-1.5s curiosity-gap / swipe-stop gate (the #1 driver)
        is_novelty_ok = novelty_score >= 7.0    # net-information-gain / swap test (anti conflict-radius cap)
        is_retention_pred_ok = retention_prediction >= 8.0
        is_topic_rec_ok = topic_recognition_score >= 8.0
        is_viewer_identity_ok = viewer_identity_score >= 8.0
        is_delayed_reveal_ok = delayed_reveal_score >= 8.0
        is_emotional_payoff_ok = emotional_payoff_score >= 7.0
        # LENGTH GATE (retention-first): cap the script so TTS lands in the 20-35s sweet spot.
        # Over-length is the #1 retention killer (your 29s Short beat the 48s one 3x), and the
        # writer routinely overshoots the stated word target, so we ENFORCE the cap here.
        _script_words = len((data.get("script") or "").split())
        data["script_words"] = _script_words
        is_length_ok = _script_words <= MAX_SCRIPT_WORDS

        attempt_ok = (
            score >= min_score_local
            and is_fidelity_ok
            and is_topic_gate_ok
            and is_title_gate_ok
            and is_hook_physical
            and is_swipe_ok
            and is_length_ok
        )
        # NOTE: the secondary scores below (first_frame, novelty, retention_prediction,
        # topic_recognition, viewer_identity, delayed_reveal, emotional_payoff) are still
        # computed and still drive the revision note (so weak ones get rewritten), but they
        # are NOT hard accept-gates. Requiring all ~14 to clear at once meant ~3/4 of scripts
        # burned all 8 attempts and fell back to "best" anyway - just far slower (up to 8 LLM
        # calls/video). We keep the gates the data actually backs - swipe-stop (the #1 driver
        # of stayed-to-watch), length (the 29s>48s finding), topic fidelity, title, and overall
        # quality - strict, and let the rest guide revision without grinding the run.
        _weak_secondary = [
            n for n, ok in (
                ("first_frame", is_first_frame_ok), ("novelty", is_novelty_ok),
                ("retention", is_retention_pred_ok), ("topic_recognition", is_topic_rec_ok),
                ("viewer_identity", is_viewer_identity_ok), ("delayed_reveal", is_delayed_reveal_ok),
                ("emotional_payoff", is_emotional_payoff_ok),
            ) if not ok
        ]
        
        # Track the fallback "best" attempt, but PREFER length-compliant scripts: a slightly
        # lower-scoring in-length script beats a higher-scoring over-length one (length is the
        # dominant retention lever), so we never ship a 48s video just because it scored well.
        _better = score > best_score
        if best is not None:
            _best_len_ok = best.get("script_words", 999) <= MAX_SCRIPT_WORDS
            if is_length_ok and not _best_len_ok:
                _better = True            # in-length always beats over-length
            elif (not is_length_ok) and _best_len_ok:
                _better = False           # never replace an in-length best with an over-length one
        if _better and (is_fidelity_ok or best is None):
            best, best_score = data, score
                
        if attempt_ok:
            data["quality_score"] = score
            print(f"[scriptgen] ACCEPTED attempt {attempt+1} score={score}")
            return data
            
        # Revision path if we didn't meet the target
        has_gate_failure = not is_title_gate_ok or not is_fidelity_ok or not is_hook_physical or not is_first_frame_ok or not is_swipe_ok or not is_novelty_ok or not is_retention_pred_ok or not is_topic_gate_ok or not is_viewer_identity_ok or not is_delayed_reveal_ok or not is_emotional_payoff_ok or not is_length_ok
        if (score >= 35.0 or has_gate_failure) and (data.get("quality_note") or has_gate_failure):
            try:
                # determine fix message — prioritize the most critical gate failure.
                # LENGTH first: an over-length script must be cut before anything else matters
                # (it's the biggest retention killer and skews every downstream timing).
                if not is_length_ok:
                    fix_message = (
                        f"CRITICAL LENGTH REJECTION: the script is {_script_words} words, over the "
                        f"{MAX_SCRIPT_WORDS}-word cap (~30s). Shorter Shorts retain far better - on THIS "
                        f"channel a 29s video got 3.2x the views of a 48s one. CUT it to {MAX_SCRIPT_WORDS} "
                        f"words or fewer: keep the hook, the single biggest reveal, and the loop ending; "
                        f"delete every secondary beat, qualifier, and repeated idea. Tighten every sentence."
                    )
                elif not is_swipe_ok:
                    fix_message = (
                        f"CRITICAL SWIPE-STOP REJECTION: swipe_stop_score={swipe_stop_score}/10 (min 7). The first "
                        f"1-1.5 seconds don't stop the swipe - this is where 50-75% of viewers leave. REWRITE the FIRST "
                        f"sentence so it does BOTH at once: (1) instantly names the familiar everyday thing (zero "
                        f"figuring-out time), and (2) opens a SPECIFIC hidden-reason gap that contradicts what they assume "
                        f"('on purpose', 'not an accident', 'it's costing you'). Frame it as a loss/manipulation. No "
                        f"preamble, no slow setup - the subject AND the 'why' itch must land in the first ~6 words."
                    )
                elif not is_novelty_ok:
                    fix_message = (
                        f"CRITICAL NOVELTY REJECTION: novelty_score={novelty_score}/10 (min 7). This is the GENERIC "
                        f"version of this idea that many channels already made - YouTube's algorithm caps that (~30k "
                        f"views). Add something genuinely NEW so it passes the swap test: a specific surprising number, "
                        f"a non-obvious SECOND mechanism, a fresh analogy, or a counterintuitive twist. Make it "
                        f"unmistakably original, not a reworded common fact."
                    )
                elif not is_hook_physical:
                    fix_message = (
                        f"CRITICAL HOOK REJECTION: The hook is classified as '{data.get('hook_type')}', NOT 'physical_moment'. "
                        f"The FIRST sentence MUST be an immediate physical action/scene (e.g., 'You walk into...', 'You grab...', 'You press...'). "
                        f"Rewrite the opening to start with a concrete physical moment the viewer has personally experienced."
                    )
                elif not is_first_frame_ok:
                    fix_message = (
                        f"CRITICAL FIRST FRAME REJECTION: first_frame_score={first_frame_score}/10 (minimum 8 required). "
                        f"The opening scene must show a SPECIFIC PHYSICAL LOCATION (airport, store, hotel, car, elevator) "
                        f"that a viewer can identify in under 0.5 seconds. Rewrite to make the setting instantly recognizable."
                    )
                elif not is_topic_rec_ok:
                    fix_message = (
                        f"CRITICAL TOPIC RECOGNITION REJECTION: topic_recognition_score={topic_recognition_score}/10 (minimum 8 required). "
                        f"The viewer must understand the topic without audio and the first frame must immediately match the title. "
                        f"Rewrite the hook and define a clear 'visual_thesis'."
                    )
                elif not is_retention_pred_ok:
                    fix_message = (
                        f"CRITICAL RETENTION REJECTION: retention_prediction={retention_prediction}/10 (minimum 8 required). "
                        f"Strengthen: scene vividness, frustration intensity, curiosity gap, and reveal payoff. "
                        f"The viewer must FEEL the annoyance before the explanation."
                    )
                elif not is_delayed_reveal_ok:
                    fix_message = (
                        f"CRITICAL STRUCTURE REJECTION: delayed_reveal_score={delayed_reveal_score}/10 (minimum 8 required). "
                        f"The biggest reveal is happening TOO EARLY. Restructure so the mystery DEEPENS through the middle "
                        f"(each sentence opens a bigger question, never resolves it), add at least two curiosity re-openings "
                        f"('but that's not even the clever part'), and push the single biggest reveal to the FINAL THIRD (70-90%). "
                        f"End on a reframe that makes the viewer go 'I'll never unsee that', not a flat stop."
                    )
                elif not is_emotional_payoff_ok:
                    fix_message = (
                        f"CRITICAL PAYOFF REJECTION: emotional_payoff_score={emotional_payoff_score}/10 (minimum 7 required). "
                        f"The ending lands as a flat 'oh, okay' instead of 'no way / I've been tricked'. Reframe the payoff to "
                        f"expose a HIDDEN INCENTIVE (who profits, what you were nudged to do, a deliberate trick). If the real "
                        f"answer is only a dry regulation/building code, find the surprising angle or the script will be rejected."
                    )
                elif not is_viewer_identity_ok:
                    fix_message = (
                        f"CRITICAL AUDIENCE IDENTITY REJECTION: viewer_identity_score={viewer_identity_score}/10 (minimum 8 required). "
                        f"The topic must be uniquely 'Hidden Logic' (exposing everyday psychological mysteries), memorable, "
                        f"discussion-generating, and emotionally relatable. Rewrite the script to make the mystery "
                        f"more universal and debate-worthy."
                    )
                elif not is_title_gate_ok:
                    fix_message = (
                        f"CRITICAL TITLE REJECTION: The title '{data.get('title')}' scored {title_score}/30 (rec={title_rec}, frust={title_frust}, cur={title_cur}). "
                        f"You MUST rewrite the title to score at least 24/30. It must be relatable, starting with 'Why...' and focus on a physical, recognizable setting and frustration."
                    )
                elif not is_fidelity_ok:
                    fix_message = (
                        f"CRITICAL TOPIC DRIFT: The script has drifted from the requested topic '{seed_topic}' "
                        f"(fidelity scored {topic_fidelity}/10, subject retention scored {subject_retention}/10). "
                        f"You MUST rewrite the script and title to be strictly and directly about '{seed_topic}'."
                    )
                else:
                    fix_message = data["quality_note"]
                    
                revised = _call(api_key, REVISE_PROMPT.format(
                    score=score, fix=fix_message, script=data["script"],
                    relatable=review.get("relatable", "?"), memory_trigger=review.get("memory_trigger", "?"),
                    hook_retention=review.get("hook_retention", "?"), surprise=review.get("surprise", "?"),
                    shareability=review.get("shareability", "?"),
                    title_score=title_score, title_recognition=title_rec,
                    title_frustration=title_frust, title_curiosity=title_cur), temperature=0.85)
                revised["topic"] = topic
                revised["filter_scores"] = filter_scores
                for k in ("title", "description", "hashtags", "broll_keywords", "emphasis_words", "first_comment", "series", "seo_keywords", "text_hook"):
                    if not revised.get(k):
                        revised[k] = data.get(k, "" if k in ("title", "description", "first_comment", "series") else [])
                
                review2 = _call(api_key, REVIEW_PROMPT.format(
                    script=revised["script"],
                    topic_lock_instruction=lock_inst,
                    seed_topic=seed_topic
                ), temperature=0.2)
                
                revised["script"] = review2.get("script", revised["script"])
                if review2.get("title"):
                    revised["title"] = review2["title"]
                # If the rewrite changed the script (e.g. fixed topic drift), the OLD description
                # may still describe the wrong topic. Prefer a fresh description from the rewrite;
                # if none provided, clear it so the description is rebuilt from the new script
                # downstream (keeps title/description/script all on the same subject).
                if review2.get("description"):
                    revised["description"] = review2["description"]
                elif review2.get("script") and review2["script"] != data.get("script"):
                    revised["description"] = ""  # force rebuild from the corrected script
                revised["factcheck"] = review2.get("issues_found", "n/a")
                revised["quality_score"] = float(review2.get("overall", 0))
                revised["quality_note"] = review2.get("fix", "")
                
                revised_fidelity = float(review2.get("topic_fidelity", 10.0))
                revised_retention = float(review2.get("subject_retention", 10.0))
                revised["topic_fidelity"] = revised_fidelity
                revised["subject_retention"] = revised_retention
                
                revised["relatable"] = review2.get("relatable", 0)
                revised["memory_trigger"] = review2.get("memory_trigger", 0)
                revised["hook_retention"] = review2.get("hook_retention", 0)
                revised["surprise"] = review2.get("surprise", 0)
                revised["shareability"] = review2.get("shareability", 0)
                
                rev_title_rec = float(review2.get("title_recognition", 0))
                rev_title_frust = float(review2.get("title_frustration", 0))
                rev_title_cur = float(review2.get("title_curiosity", 0))
                rev_title_score = rev_title_rec + rev_title_frust + rev_title_cur
                
                revised["title_recognition"] = rev_title_rec
                revised["title_frustration"] = rev_title_frust
                revised["title_curiosity"] = rev_title_cur
                revised["title_score"] = rev_title_score
                revised["hook_type"] = review2.get("hook_type", "explainer")
                
                revised["first_frame_score"] = float(review2.get("first_frame_score", 0))
                revised["retention_prediction"] = float(review2.get("retention_prediction", 0))
                revised["topic_recognition_score"] = float(review2.get("topic_recognition_score", 0))
                revised["viewer_identity_score"] = float(review2.get("viewer_identity_score", 0))
                revised["delayed_reveal_score"] = float(review2.get("delayed_reveal_score", 0))
                revised["emotional_payoff_score"] = float(review2.get("emotional_payoff_score", 0))
                revised["visual_thesis"] = review2.get("visual_thesis", "")
                revised["taxonomy"] = review2.get("taxonomy", "")
                revised["hook_structure"] = review2.get("hook_structure", "")
                revised["first_frame_description"] = review2.get("first_frame_description", "")
                revised["predicted_views_score"] = float(review2.get("predicted_views_score", 0))
                
                revised["environment_score"] = env_score
                revised["annoyance_score"] = ann_score
                revised["universality_score"] = univ_score
                revised["winner_cluster_score"] = float(filter_scores.get("winner_similarity", 0))
                revised["visual_score"] = float(filter_scores.get("visual", 0))
                
                revised_fidelity_ok = (not strict_topic_lock) or (revised_fidelity >= 8.0 and revised_retention >= 8.0)
                revised_title_gate_ok = rev_title_score >= 24 and rev_title_frust >= 7.0
                revised_topic_gate_ok = is_topic_gate_ok
                revised_hook_physical = revised.get("hook_type") == "physical_moment"
                revised_first_frame_ok = float(revised.get("first_frame_score", 0)) >= 8.0
                revised_retention_pred_ok = float(revised.get("retention_prediction", 0)) >= 8.0
                revised_topic_rec_ok = float(revised.get("topic_recognition_score", 0)) >= 8.0
                revised_viewer_identity_ok = float(revised.get("viewer_identity_score", 0)) >= 8.0
                revised_delayed_reveal_ok = float(revised.get("delayed_reveal_score", 0)) >= 8.0
                revised_emotional_payoff_ok = float(revised.get("emotional_payoff_score", 0)) >= 7.0
                
                revised_ok = (
                    revised["quality_score"] >= min_score_local
                    and revised_fidelity_ok
                    and revised_topic_gate_ok
                    and revised_title_gate_ok
                    and revised_hook_physical
                    and revised_first_frame_ok
                    and revised_retention_pred_ok
                    and revised_topic_rec_ok
                    and revised_viewer_identity_ok
                    and revised_delayed_reveal_ok
                    and revised_emotional_payoff_ok
                )
                
                print(f"[scriptgen] revised near-miss: {score} -> {revised['quality_score']} (fidelity {revised_fidelity}/10, retention {revised_retention}/10, title {rev_title_score}/30, first_frame {revised.get('first_frame_score', 0)}/10, ret_pred {revised.get('retention_prediction', 0)}/10, hook={revised.get('hook_type')})")
                
                if revised["quality_score"] > best_score:
                    if revised_fidelity_ok or best is None:
                        best, best_score = revised, revised["quality_score"]
                if revised_ok:
                    print(
                        f"[scriptgen] ACCEPTED revised attempt "
                        f"{attempt+1} score={revised['quality_score']}"
                    )
                    data = revised
                    accepted_this_attempt = True
            except Exception as rev_err:
                print(f"[scriptgen] Revision attempt failed: {rev_err}")

        if accepted_this_attempt:
            break

    if not accepted_this_attempt:
        data = best
    print(f"[scriptgen] quality score {best_score}/50 after {attempt+1} attempt(s)")
    
    # RUTHLESS QUALITY GATING (V5: includes hook, first_frame, retention gates)
    final_title_score = data.get("title_score", 0)
    final_hook_type = data.get("hook_type", "explainer")
    final_first_frame = float(data.get("first_frame_score", 0))
    final_retention_pred = float(data.get("retention_prediction", 0))
    final_topic_rec = float(data.get("topic_recognition_score", 0))
    final_viewer_identity = float(data.get("viewer_identity_score", 0))
    final_delayed_reveal = float(data.get("delayed_reveal_score", 0))
    final_emotional_payoff = float(data.get("emotional_payoff_score", 0))
    
    is_final_ok = (
        best_score >= quality_floor_local
        and final_title_score >= 24
        and float(data.get("title_frustration", 0)) >= 7.0
        and final_hook_type == "physical_moment"
        and final_first_frame >= 8.0
        and final_retention_pred >= 8.0
        and final_topic_rec >= 8.0
        and final_viewer_identity >= 8.0
        and final_delayed_reveal >= 8.0
        and final_emotional_payoff >= 7.0
    )
    
    # Determine the primary rejection reason for slot stats tracking
    if not is_final_ok:
        if final_hook_type != "physical_moment":
            reject_reason = "hook_not_physical"
        elif final_first_frame < 8.0:
            reject_reason = "first_frame_low"
        elif final_delayed_reveal < 8.0:
            reject_reason = "reveal_too_early"
        elif final_emotional_payoff < 7.0:
            reject_reason = "weak_emotional_payoff"
        elif final_topic_rec < 8.0:
            reject_reason = "topic_recognition_low"
        elif final_retention_pred < 8.0:
            reject_reason = "retention_pred_low"
        elif final_viewer_identity < 8.0:
            reject_reason = "viewer_identity_low"
        elif final_title_score < 24:
            reject_reason = "title_score_low"
        else:
            reject_reason = "quality_floor"
        raise RuntimeError(
            f"QUALITY & GATING REJECTION [{reject_reason}]: Best attempt failed gates "
            f"(score={best_score}/50, title={final_title_score}/30, hook={final_hook_type}, "
            f"first_frame={final_first_frame}/10, ret_pred={final_retention_pred}/10, viewer_identity={final_viewer_identity}/10). Sacrificing slot."
        )

    # Subcluster Cooldown Gate (30 days)
    if data.get("taxonomy"):
        recent_taxonomies = set()
        if os.path.exists("channel_index.json"):
            try:
                import datetime as dt
                with open("channel_index.json", encoding="utf-8") as f:
                    idx = json.load(f)
                thirty_days_ago = (dt.datetime.now() - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
                for entry in idx:
                    if entry.get("date") and entry["date"] >= thirty_days_ago:
                        if entry.get("taxonomy"):
                            recent_taxonomies.add(entry["taxonomy"])
            except Exception as e:
                print(f"[scriptgen] Error reading channel_index for taxonomy cooldown: {e}")
        if data["taxonomy"] in recent_taxonomies:
            raise RuntimeError(f"QUALITY & GATING REJECTION [subcluster_clone]: Taxonomy '{data['taxonomy']}' was used in the last 30 days. Sacrificing slot.")

        
    if "topic" not in data:
        data["topic"] = topic
    fs = data.get("filter_scores", {}) or filter_scores
    data["relatability_score"] = data.get("relatable", 0)
    data["memory_trigger_score"] = data.get("memory_trigger", 0)
    data["curiosity_score"] = fs.get("curiosity", 0)
    data["visual_score"] = fs.get("visual", 0)
    data["environment_bonus"] = fs.get("environment_bonus", 0)
    
    cluster, bonus = winner_memory.get_winner_bonus(data["topic"])
    data["cluster"] = cluster
    data["winner_bonus"] = bonus
    
    data["topic_fidelity"] = data.get("topic_fidelity", 10.0)
    data["subject_retention"] = data.get("subject_retention", 10.0)
    
    data.setdefault("broll_keywords", ["cinematic", "documentary shot", "slow motion"])
    data.setdefault("emphasis_words", [])
    data.setdefault("series", "Everyday Design")
    data.setdefault("seo_keywords", [])
    if not data.get("series"):
        data["series"] = "Everyday Design"
    return data
