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
    """Use a bounded stable model chain, never every discovered preview model."""
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
        # Discovery is availability information, not a quality or quota ranking.
        # Keep the known production preference order and at most three models.
        preferred = [name for name in MODELS if name in names]
        if preferred:
            _discovered = preferred
            print(f"[scriptgen] bounded production model chain: {_discovered}")
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

    # PERFORMANCE FLOOR: the channel's own data shows a ~10x view spread by cluster - relatable
    # PLACE/OBJECT topics (emotions~1071, decisions~1048, airline~1037, supermarket~666) pull an
    # order of magnitude more than abstract INTERNAL topics (memory~124, technology~106). Those
    # low clusters are boring-lecture material no hook can save, and the bank has 90+ proven
    # place-topics queued, so there is no reason to ever spend a slot on them. We hard-drop any
    # cluster whose average views sit below a floor, UNLESS it's brand-new (no videos yet, so it
    # deserves a few exploration shots) or it's a live trend seed. Floor is config-tunable.
    def _early_cfg_get(key, default):
        try:
            import config_loader
            return config_loader.load_config("config.json").get(key, default)
        except Exception:
            try:
                import json as _j, os as _o
                if _o.path.exists("config.json"):
                    with open("config.json", encoding="utf-8") as _f:
                        return _j.load(_f).get(key, default)
            except Exception:
                pass
        return default
    _floor = float(_early_cfg_get("min_cluster_avg_views", 200.0))
    def _cluster_avg(c):
        info = clusters_info.get(c, {}) or {}
        return float(info.get("avg_views", 0.0)), int(info.get("videos", 0) or 0)
    _floored = []
    for c in list(sorted_clusters):
        avg, vids = _cluster_avg(c)
        # keep unproven clusters (vids < 5) so exploration still happens; drop proven duds.
        if vids >= 5 and avg < _floor:
            _floored.append(c)
    if _floored:
        sorted_clusters = [c for c in sorted_clusters if c not in _floored]
        available_clusters = [c for c in available_clusters if c not in _floored]
        top_3 = sorted_clusters[:3]
        print(f"[scriptgen] Performance floor ({_floor:.0f} views): dropped low-view clusters "
              f"{sorted(_floored)}; steering to proven place/object topics. Top now: {top_3}")
    
    # Exploit seeds: seeds belonging to top_3 clusters
    exploit_seeds = []
    for c in top_3:
        exploit_seeds.extend(winner_memory.ADJACENT_SEEDS.get(c, []))
        
    # Explore seeds: seeds from other available clusters, plus general seeds that don't belong to cooldowns
    explore_seeds = []
    other_clusters = [c for c in available_clusters if c not in top_3]
    for c in other_clusters:
        explore_seeds.extend(winner_memory.ADJACENT_SEEDS.get(c, []))
        
    _blocked = set(cooldowns) | set(_floored)
    for s in SEEDS:
        c = winner_memory.detect_cluster(s)
        if c and c in _blocked:
            continue
        if s not in exploit_seeds and s not in explore_seeds:
            explore_seeds.append(s)

    if not explore_seeds:
        explore_seeds = [s for s in SEEDS if winner_memory.detect_cluster(s) not in _blocked]
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


WRITE_PROMPT = """Write one Hidden Logic everyday explainer about {topic}.
Target 55-75 spoken words initially; actual narration must later be measured for 20-26 seconds.
Start with a concrete familiar object and a specific question or contradiction the viewer can picture.
Avoid disconnected fragments such as 'Same barcode. Different price.' Give a useful explanation within the first
15 words, then show how it works. Use contractions and varied sentence lengths that sound natural
when spoken. Explain one mechanism, with a concrete example. Finish the answer completely.
Do not demand a villain, manipulation, universal behaviour, a numerical fact, or a twist.
Never invent motives, measurements or sources. Preserve exceptions and uncertainty.
No generic suspense, 'here's the kicker', 'but that's not even the clever part', 'you've been
tricked', 'this isn't an accident', compulsory curiosity pivots or unfinished loop endings.
Resolve the opening question with a short callback to its object or situation, then end with
one short spoken invitation to follow Hidden Logic for
more everyday explanations. Include this CTA in the word budget; no requests to like, share and comment.
Follow one object through one connected situation: observation, mechanism, consequence, invitation.
Use connected explanatory phrases, not a string of dramatic fragments or a checklist of facts.
Use topic-specific nouns and actions. A plain accurate answer beats a dramatic invented one.
Write a specific truthful title and optional 2-5 word text_hook without exaggeration.
Provide six concrete stock-footage search phrases in narration order, each describing a visible
subject and action. Carry the same concrete object and setting through every query, including the
closing shot; don't jump between unrelated products just because they share a topic. Match the actual object: scanning a barcode is not scanning a QR code or
paying by card. Keep places ordinary. No abstract filler, spooky atmosphere or decorative graphics.
visual_thesis should explain what the footage needs to show. Give at most two emphasis_words.
Use a suitable series, concrete SEO keywords and three relevant hashtags including #shorts.
first_comment must be one specific, easy-to-answer question about the viewer's experience of
this situation. No generic engagement bait. Provide sound_cues: at most two objects with phrase
(an exact unique phrase in the narration) and kind (scan or chime), only at meaningful payoff
moments. Use scan only when a scanner is involved; never arbitrary transition sounds.
Never add spoken production directions to script. Keep the callback and CTA natural; do not
speed up to squeeze a long ending into two seconds.
Respond ONLY with JSON:
{{"script": "...", "title": "...", "description": "...", "taxonomy": "...", "visual_thesis": "...", "series": "...", "text_hook": "...", "seo_keywords": ["..","..","..",".."], "hashtags": ["#shorts","#hiddenlogic","..",".."], "broll_keywords": ["..","..","..","..","..",".."], "emphasis_words": ["..",".."], "first_comment": "...", "sound_cues": [{{"phrase":"unique payoff phrase", "kind":"chime"}}]}}"""

REVIEW_PROMPT = """Review this Hidden Logic explainer as an editor, not as a predictor of views.
Seed: {seed_topic}
{topic_lock_instruction}
Script: {script}
Correct unsupported certainty, implied motives, generic suspense, repetition and awkward spoken
phrasing. Do not add facts or numbers to make it more exciting. Model review is not source verification;
flag claims needing primary-source support in issues_found. A simple accurate explanation can score well.
Score every requested numeric field from 0 to 10, with overall the sum of relatable, memory_trigger,
hook_retention, surprise and shareability (0-50). Retention and views scores are editorial opinions only.
answer_clarity_score measures EARLY USEFUL ANSWER AND CLEAR PROGRESSION: high only when the answer begins within the first 15 words and is explained fully.
emotional_payoff_score means a complete, useful resolution; never require outrage or manipulation.
title_frustration means a recognizable concrete situation, not forced frustration. Novelty means a
specific useful angle or demonstration, not invented numbers. hook_type can be physical_moment or
explainer; neither is automatically better. first_frame_description must be a filmable relevant action.
The first frame must have one clear, well-lit focal object already visible, with no fade or
transition. Avoid a busy shelf with no focal point. The closing shot returns to that object.
Return corrected narration, an accurate title, and one actionable fix. Never insert a cliffhanger.
Check that the opening poses a concrete question, every sentence advances its answer, the resolution
refers back to the opening situation, and the final
short spoken invitation to follow Hidden Logic comes AFTER the complete resolution. Preserve this CTA.
Flag disconnected fragments, a generic hook, missing CTA, or changes of object/setting in issues_found.
Also return sound_cues (zero to two phrase/kind objects) using unique exact phrases in your
corrected narration, and first_comment as one specific viewer-experience question ending in '?'.
Respond ONLY with JSON:
{{"issues_found": "facts note or 'none'", "script": "final corrected script", "title": "corrected title", "taxonomy": "cluster/subcluster", "visual_thesis": "...", "hook_structure": "...", "first_frame_description": "...", "relatable": n, "memory_trigger": n, "hook_retention": n, "surprise": n, "shareability": n, "overall": n, "title_recognition": n, "title_frustration": n, "title_curiosity": n, "hook_type": "physical_moment" or "explainer", "topic_fidelity": n, "subject_retention": n, "first_frame_score": n, "swipe_stop_score": n, "novelty_score": n, "retention_prediction": n, "topic_recognition_score": n, "predicted_views_score": n, "viewer_identity_score": n, "answer_clarity_score": n, "emotional_payoff_score": n, "fix": "one sentence on the biggest weakness"}}"""


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
MAX_SCRIPT_WORDS = 100  # hard ceiling; raised from 78 to permit the 30-38s TEST variant below.
                        # The 78-word/29s finding came from the ROBOTIC-VOICE era (a bad voice makes
                        # every extra second painful). 2026 research: sub-15s collapsed (can't clear
                        # the absolute watch-time bar) and 30-45s is the new sweet spot. With the
                        # human Gemini voice live, we A/B a longer variant at low weight and let the
                        # channel's own retention data decide. Most videos still target 16-29s.

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
    "82 to 100 words (about 31-38 seconds - TEST variant, 2026 research band). Use a two-beat "
    "structure: hook -> first reveal -> escalation ('but here's the part nobody notices') -> "
    "deeper payoff -> loop. The extra length must be a SECOND curiosity peak, never slower "
    "pacing. HARD CAP at 100 words.",
]

# Repurposable curiosity-gap hook PATTERNS, distilled from proven scroll-stopping short-form
# openers (information-gap theory + open loops + negativity bias). The writer rotates a few of
# these per video so hooks stay fresh AND always open a specific gap in the first ~1 second.
# This is the "repurpose proven hooks" engine: unlimited fresh hooks from a small set of structures.
CURIOSITY_HOOK_PATTERNS = ['Name an observable mismatch.', 'Show the object in use.', 'Ask a specific everyday question.', 'Start with a concrete comparison.']

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
    length_rule = _rnd.choices(_LENGTH_VARIANTS, weights=[60, 25, 5, 10])[0]  # 10% = 30-38s A/B test
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
    for _model_idx, model in enumerate(_best_models(api_key)):
        if model in _dead_models:
            continue
        # The top premium models write dramatically better scripts than the lite fallbacks
        # ("airlines are leaking your plane"-grade mush comes from the lite end of the chain).
        # Give the first two premium models 3 attempts with growing backoff before sliding
        # down; everything below keeps the fast 2-attempt behavior.
        _max_tries = 3 if _model_idx < 2 else 2
        for attempt in range(_max_tries):
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
                    # from 429 (our quota). Count a hit only when a MODEL IS EXHAUSTED (all its
                    # retries spent), not per response - otherwise the premium retries above
                    # would trip the fleet-bail on a single busy model.
                    last_err = RuntimeError(f"{r.status_code} from {model} (Google server busy, not a quota issue)")
                    if attempt < _max_tries - 1:
                        _wait = 5 * (attempt + 1) * (attempt + 1)  # 5s, 20s
                        print(f"[scriptgen] {model} returned {r.status_code} (server busy, not quota), "
                              f"retry {attempt + 1}/{_max_tries - 1} in {_wait}s...")
                        time.sleep(_wait)
                        continue
                    server_busy_hits += 1
                    if server_busy_hits >= SERVER_BUSY_TRIP:
                        raise _GeminiQuotaExhausted(
                            f"Gemini servers busy ({server_busy_hits} models exhausted with 5xx this call). "
                            f"This is a Google-side outage, not your quota - handing off to Claude.",
                            is_server_busy=True,
                        )
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

REVISE_PROMPT = """Revise this existing script to address the editor's specific issue: {fix}
Script: {script}
Keep 55-75 words, a useful answer in the first 15 words, and a complete explanation.
Preserve supported facts and qualifiers. No new numerical or causal claims without evidence.
Use specific observations, conversational phrasing and varied sentence length. Remove repetition,
forced suspense, claims of hidden intent, stock AI phrases and incomplete loop endings.
Keep footage queries literal, in narration order, and consistent with the revised subject.
Keep the same concrete object and setting throughout. Make the hook a recognizable question or
contradiction, join choppy fragments, and preserve one short spoken invitation to follow Hidden Logic
after the full answer and a concise callback to the opening situation. The invitation counts toward the word budget.
Respond ONLY with JSON (keep title/description/hashtags/broll_keywords/emphasis_words consistent with the new script):
{{"script": "...", "title": "...", "description": "...", "hashtags": ["#shorts","#hiddenlogic","..",".."], "broll_keywords": ["..","..","..","..","..",".."], "emphasis_words": ["..",".."], "first_comment": "...", "sound_cues": [{{"phrase":"unique payoff phrase", "kind":"chime"}}]}}"""

import random

SERIES_FORMATS = ['Everyday technology', 'Queues and travel', 'Shopping and pricing']

# Author the executable visual plan with the first script, and preserve it through
# automatic editorial review. Braces are escaped for the legacy .format interface.
from production_brief import RULES as _PRODUCTION_RULES
from credible.storyboard import SCHEMA as _DRAWING_SCHEMA
_PRODUCTION_INSTRUCTIONS = ('\n'+_PRODUCTION_RULES+_DRAWING_SCHEMA).replace('{','{{').replace('}','}}')
WRITE_PROMPT += _PRODUCTION_INSTRUCTIONS
REVIEW_PROMPT += _PRODUCTION_INSTRUCTIONS
REVISE_PROMPT += _PRODUCTION_INSTRUCTIONS

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
    from credible.legacy_topics import generate as sourced_generate
    return sourced_generate(api_key, topic)


def _legacy_generate_archived(api_key: str, topic: str | None = None, extra_guidance: str = "",
             rater_benchmark: str = "", variant: str = "A", strict_topic_lock: bool = False,
             publish_at: str | None = None) -> dict:
    """Historical prompt implementation; production uses the shared sourced writer."""
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
        prompt += "\n\nExplain the observation, show the mechanism, finish with its practical implication."
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
        for field in ('beats','storyboard','broll_keywords'):
            if field in review: data[field] = review[field]
        data['sound_cues'] = review.get('sound_cues', [])
        data['first_comment'] = review.get('first_comment', data.get('first_comment', ''))
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
        answer_clarity_score = float(review.get("answer_clarity_score", 0))
        emotional_payoff_score = float(review.get("emotional_payoff_score", 0))
        data["first_frame_score"] = first_frame_score
        data["swipe_stop_score"] = swipe_stop_score
        data["novelty_score"] = novelty_score
        data["retention_prediction"] = retention_prediction
        data["topic_recognition_score"] = topic_recognition_score
        data["viewer_identity_score"] = viewer_identity_score
        data["answer_clarity_score"] = answer_clarity_score
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
        
        # TREND MISMATCH GUARD: for TREND seeds, fidelity is a HARD gate regardless of the
        # strict_topic_lock config. A trend title (e.g. an F1 race) attracts that trend's
        # audience specifically - if the script drifts to a different subject (e.g. generic
        # highway driving), those viewers hit a bait-and-switch and swipe instantly, which
        # kills the video AND teaches the algorithm the channel mismatches its packaging.
        # (Real case: "Why You Can't Catch The Leader On The Last Lap" - racing title,
        # semi-truck tailgating script.) Normal evergreen topics keep the configurable gate.
        _is_trend = False
        try:
            import trend_bridge as _tb
            _is_trend = bool(seed_topic) and _tb.is_trend_seed(seed_topic)
        except Exception:
            _is_trend = False
        if _is_trend:
            is_fidelity_ok = (topic_fidelity >= 8.0 and subject_retention >= 8.0)
            if not is_fidelity_ok:
                print(f"[scriptgen] TREND MISMATCH GUARD: trend seed '{seed_topic}' but fidelity "
                      f"{topic_fidelity}/10, subject retention {subject_retention}/10 - blocking "
                      f"(trend titles must match their content or viewers bait-and-switch swipe).")
        else:
            is_fidelity_ok = (not strict_topic_lock) or (topic_fidelity >= 8.0 and subject_retention >= 8.0)
        # When the topic is PINNED (idea bank, --hero trend, on-demand) the topic-filter
        # never runs, so filter_scores is empty and "visual" is 0. The old code therefore
        # made this gate ALWAYS fail for pinned topics, forcing every such video to burn all
        # MAX_ATTEMPTS (~8x the LLM cost) before shipping anyway. Pinned topics are pre-vetted,
        # so they pass the topic gate by definition.
        is_topic_gate_ok = pinned or float(filter_scores.get("visual", 0)) >= 8.0
        is_title_gate_ok = title_score >= 24 and title_frust >= 7.0
        is_hook_physical = data.get("hook_type") in ("physical_moment", "explainer")
        is_first_frame_ok = first_frame_score >= 8.0
        is_swipe_ok = swipe_stop_score >= 7.0   # first-1.5s curiosity-gap / swipe-stop gate (the #1 driver)
        is_novelty_ok = novelty_score >= 7.0    # net-information-gain / swap test (anti conflict-radius cap)
        is_retention_pred_ok = retention_prediction >= 8.0
        is_topic_rec_ok = topic_recognition_score >= 8.0
        is_viewer_identity_ok = viewer_identity_score >= 8.0
        is_answer_clarity_ok = answer_clarity_score >= 8.0
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
        # topic_recognition, viewer_identity, answer_clarity, emotional_payoff) are still
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
                ("viewer_identity", is_viewer_identity_ok), ("answer_clarity", is_answer_clarity_ok),
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
        has_gate_failure = not is_title_gate_ok or not is_fidelity_ok or not is_hook_physical or not is_first_frame_ok or not is_swipe_ok or not is_novelty_ok or not is_retention_pred_ok or not is_topic_gate_ok or not is_viewer_identity_ok or not is_answer_clarity_ok or not is_emotional_payoff_ok or not is_length_ok
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
                        f"words or fewer: keep the observation, useful mechanism, and complete ending; "
                        f"delete every secondary beat, qualifier, and repeated idea. Tighten every sentence."
                    )
                elif not is_swipe_ok:
                    fix_message = (
                        f"CRITICAL SWIPE-STOP REJECTION: swipe_stop_score={swipe_stop_score}/10 (min 7). The first "
                        f"1-1.5 seconds don't stop the swipe - this is where 50-75% of viewers leave. REWRITE the FIRST "
                        f"sentence so it does BOTH at once: (1) instantly names the familiar everyday thing (zero "
                        f"figuring-out time), and (2) opens a SPECIFIC hidden-reason gap that contradicts what they assume "
                        f"using a concrete observation. Do not invent intent or manipulation. No "
                        f"preamble, no slow setup - the subject AND the 'why' itch must land in the first ~6 words."
                    )
                elif not is_novelty_ok:
                    fix_message = "Make the explanation concrete with a useful observation or demonstration. Do not add unverified numbers or causes."
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
                elif not is_answer_clarity_ok:
                    fix_message = "Give the first useful answer within 15 words, then explain it. Do not withhold the mechanism."
                elif not is_emotional_payoff_ok:
                    fix_message = "Finish the explanation with a concrete implication. Do not invent a hidden incentive or force outrage."
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
                for k in ("title", "description", "hashtags", "broll_keywords", "emphasis_words", "first_comment", "series", "seo_keywords", "text_hook", "sound_cues"):
                    if not revised.get(k):
                        revised[k] = data.get(k, "" if k in ("title", "description", "first_comment", "series") else [])
                
                review2 = _call(api_key, REVIEW_PROMPT.format(
                    script=revised["script"],
                    topic_lock_instruction=lock_inst,
                    seed_topic=seed_topic
                ), temperature=0.2)
                
                revised["script"] = review2.get("script", revised["script"])
                for field in ('beats','storyboard','broll_keywords'):
                    if field in review2: revised[field] = review2[field]
                revised['sound_cues'] = review2.get('sound_cues', [])
                revised['first_comment'] = review2.get('first_comment', revised.get('first_comment', ''))
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
                revised["answer_clarity_score"] = float(review2.get("answer_clarity_score", 0))
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
                
                # Trend seeds keep the HARD fidelity gate on revision too (see trend mismatch guard above).
                if _is_trend:
                    revised_fidelity_ok = (revised_fidelity >= 8.0 and revised_retention >= 8.0)
                else:
                    revised_fidelity_ok = (not strict_topic_lock) or (revised_fidelity >= 8.0 and revised_retention >= 8.0)
                revised_title_gate_ok = rev_title_score >= 24 and rev_title_frust >= 7.0
                revised_topic_gate_ok = is_topic_gate_ok
                revised_hook_physical = revised.get("hook_type") in ("physical_moment", "explainer")
                revised_first_frame_ok = float(revised.get("first_frame_score", 0)) >= 8.0
                revised_retention_pred_ok = float(revised.get("retention_prediction", 0)) >= 8.0
                revised_topic_rec_ok = float(revised.get("topic_recognition_score", 0)) >= 8.0
                revised_viewer_identity_ok = float(revised.get("viewer_identity_score", 0)) >= 8.0
                revised_answer_clarity_ok = float(revised.get("answer_clarity_score", 0)) >= 8.0
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
                    and revised_answer_clarity_ok
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
    final_answer_clarity = float(data.get("answer_clarity_score", 0))
    final_emotional_payoff = float(data.get("emotional_payoff_score", 0))
    
    is_final_ok = (
        best_score >= quality_floor_local
        and final_title_score >= 24
        and float(data.get("title_frustration", 0)) >= 7.0
        and final_hook_type in ("physical_moment", "explainer")
        and final_first_frame >= 8.0
        and final_retention_pred >= 8.0
        and final_topic_rec >= 8.0
        and final_viewer_identity >= 8.0
        and final_answer_clarity >= 8.0
        and final_emotional_payoff >= 7.0
    )
    
    # Determine the primary rejection reason for slot stats tracking
    if not is_final_ok:
        if final_hook_type not in ("physical_moment", "explainer"):
            reject_reason = "hook_not_physical"
        elif final_first_frame < 8.0:
            reject_reason = "first_frame_low"
        elif final_answer_clarity < 8.0:
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
    
    if not re.search(r"\b(?:follow|subscribe to)\s+Hidden\s+Logic\b", " ".join(data["script"].split()[-22:]), re.I):
        raise ValueError("Final narration is missing its closing Hidden Logic invitation")
    if not data.get("broll_keywords"):
        raise ValueError("Concrete footage queries are required; generic filler is disabled")
    if not str(data.get('first_comment', '')).strip().endswith('?'):
        raise ValueError('A topic-specific viewer question is required for the first comment')
    data.setdefault("emphasis_words", [])
    data.setdefault("series", "Everyday Design")
    data.setdefault("seo_keywords", [])
    if not data.get("series"):
        data["series"] = "Everyday Design"
    return data
