import json
import os
import datetime

MEMORY_FILE = "winner_memory.json"
CLUSTERS = [
    # Banned clusters (still defined so old index parses, but banned from generator)
    "airport", "hotel", "airline", "mall", "traffic", "escalator", "elevator", "gas_station", "restaurant", "supermarket", "retail_layout", "brain", "social",
    # V2 Active clusters
    "memory", "attention", "perception", "social_behavior", "cognitive_bias",
    "technology", "internet_behavior", "decision_making", "habits", "emotions", "money_psychology"
]

ADJACENT_SEEDS = {
    # V1 Seeds (archived/banned from generation, but kept for statistical fallback lookup)
    "airport": [
        "airport carpets", "airport gate changes", "airport moving walkways", 
        "airport seating", "airport boarding groups", "airport announcements", 
        "airport duty free", "airport security queues", "airport baggage claim", 
        "airport signs", "airport walks being so long", "airport food costing so much",
        "sleeping at the airport", "airport terminal layouts"
    ],
    "hotel": [
        "hotel curtains", "hotel showers", "hotel mini bars", "hotel lighting", 
        "hotel keycards", "hotel mirrors", "hotel hallways feeling endless", "hotel breakfast buffets",
        "hotel rooms feeling familiar", "hotel pillows being so big", "hotel bathroom design",
        "hotel pillows being the worst"
    ],
    "supermarket": [
        "milk placement at the back", "grocery layout design", "supermarket bakery smells",
        "bakeries being near entrances", "shopping carts getting bigger", "grocery stores spraying water",
        "eggs never being near bread", "sale signs tricking you", "grocery stores moving products",
        "self checkout machine design", "supermarket aisle layouts", "supermarket milk being at the back",
        "IKEA forcing one-way walking", "checkout lines being designed that way",
        "milk at the back", "freshest milk is always hidden"
    ],
    "traffic": [
        "traffic jam delays", "slow lanes moving faster", "merging causing traffic out of nowhere",
        "red lights feeling longer", "highway layouts", "picking the wrong lane in traffic",
        "road signs placement", "streetlights placement", "traffic appearing out of nowhere",
        "traffic never moves"
    ],
    "elevator": [
        "elevator buttons closing doors that don't work", "staring at the floor in elevators", "elevator mirrors existing",
        "elevator music", "elevator arrival bells", "escalator safety features", "escalator brush design",
        "elevator floors"
    ],
    "gas_station": [
        "gas station layouts", "gas station snacks", "buying more at the gas station", "gas station pricing", "gas pump design"
    ],
    "mall": [
        "theme park gift shops", "movie theater sticky floors", "casinos having no clocks",
        "casinos having no windows", "duty-free stores being unavoidable", "shopping mall layouts",
        "office buildings lobbies", "school hallways design"
    ],
    "restaurant": [
        "restaurant menus removing favorites", "fast food menus constantly changing", "restaurant layouts",
        "fast food drive through design", "waiter behavior", "vending machine design", "buffet layouts"
    ],
    "airline": [
        "airline seat size", "airline boarding groups", "flight delays", "paying for carry-on luggage",
        "airline meal quality", "window seat vs aisle seat", "airplane bathroom layouts"
    ],
    "brain": [
        "forgetting why you entered a room", "names disappearing instantly", "songs getting stuck in your head",
        "names disappearing from memory", "recognizing faces but forgetting names", "time speeding up as you age",
        "waiting feeling longer when watched", "waking up 5 minutes before your alarm", "hitting the snooze button repeatedly",
        "your brain waking before alarms"
    ],
    "social": [
        "everyone choosing the wrong queue", "nobody sitting next to you on the bus", "people speeding up when you overtake them",
        "waiting in line", "people hating slow walkers", "staring at the floor in elevators"
    ],
    # V2 Active Seeds
    "memory": [
        "forgetting why you entered a room", "remembering embarrassing moments forever", "names being so easy to forget", "not being able to remember most dreams"
    ],
    "attention": [
        "feeling your phone vibrate when it didn't", "songs getting stuck in your head", "waking up before your alarm"
    ],
    "perception": [
        "suddenly seeing the same car everywhere", "time feeling faster as you age"
    ],
    "social_behavior": [
        "everyone picking the wrong queue", "awkward silences feeling longer", "people copying accents", "hating slow walkers", "people interrupting each other"
    ],
    "cognitive_bias": [
        "everyone thinking they are above average"
    ],
    "technology": [
        "phone notifications being red"
    ],
    "internet_behavior": [
        "clicking on clickbait", "online arguments feeling endless", "scrolling past what you want to read"
    ],
    "decision_making": [
        "buying things you don't need", "buying more than you planned"
    ],
    "habits": [
        "checking your phone without thinking", "rewatching the same shows"
    ],
    "emotions": [
        "loving winning arguments", "laughing when nervous"
    ],
    "money_psychology": [
        "free shipping working on you", "everything ending in .99"
    ]
}

def detect_cluster(title: str, topic: str = "") -> str | None:
    t = (title + " " + topic).lower()
    if "airport" in t:
        return "airport"
    if "hotel" in t:
        return "hotel"
    if any(w in t for w in ["supermarket", "grocery", "ikea", "checkout", "shopping cart", "bakery", "bakeries", "milk", "eggs", "veggies", "vegetables", "aisle"]):
        return "supermarket"
    if any(w in t for w in ["traffic", "road", "lane", "car", "highway", "streetlights", "streetlight"]):
        return "traffic"
    if any(w in t for w in ["elevator", "escalator"]):
        return "elevator"
    if "gas station" in t or "gas pump" in t or "fuel station" in t:
        return "gas_station"
    if any(w in t for w in ["restaurant", "dining", "menu", "buffet", "waiter", "fast food", "drive through"]):
        return "restaurant"
    if any(w in t for w in ["airline", "flight", "boarding group", "plane", "airplane", "flying"]):
        return "airline"
    if any(w in t for w in ["mall", "theme park", "gift shop", "casino", "movie theater", "cinema"]):
        return "mall"
    if "retail layout" in t or "store layout" in t:
        return "retail_layout"
        
    # V2 Active clusters
    if any(w in t for w in ["forgetting why", "forgetting names", "remembering embarrassing", "remember most dreams", "dream", "dreams", "memory", "remembering", "forget", "forgetting"]):
        return "memory"
    if any(w in t for w in ["vibrate", "vibration", "song", "songs", "earworm", "alarm", "waking", "wake up before", "attention"]):
        return "attention"
    if any(w in t for w in ["see the same", "car everywhere", "notice the same", "time feels faster", "age", "perception"]):
        return "perception"
    if any(w in t for w in ["queue", "wrong queue", "awkward silence", "silence", "silences", "copy accents", "accent", "slow walkers", "interrupt", "interrupting", "social"]):
        return "social_behavior"
    if any(w in t for w in ["above average", "bias", "cognitive"]):
        return "cognitive_bias"
    if any(w in t for w in ["phone", "app", "netflix", "autoplay", "cookie", "website", "rating", "notification", "notifications", "scroll", "screen", "technology"]):
        return "technology"
    if any(w in t for w in ["clickbait", "argument", "arguments", "scroll past", "internet"]):
        return "internet_behavior"
    if any(w in t for w in ["buy things", "buying", "planned", "menu", "favorites", "changing", "removing", "decision"]):
        return "decision_making"
    if any(w in t for w in ["check your phone", "without thinking", "rewatch", "habit", "habits", "nail", "nails", "routine", "routines"]):
        return "habits"
    if any(w in t for w in ["winning arguments", "win arguments", "bad news", "clutter", "anxious", "laugh", "laughing", "nervous", "emotion", "emotions", "feeling"]):
        return "emotions"
    if any(w in t for w in ["free shipping", "ending in .99", "sales feel", "sale", "price", "spending", "money", "coupon", "coupons"]):
        return "money_psychology"
        
    # fallback to seed match
    for cluster, seeds in ADJACENT_SEEDS.items():
        for seed in seeds:
            if seed in t:
                return cluster
    return None


# Strong football/soccer-era signals. The channel pivoted away from football, but ~77
# football videos still sit in channel_index.json and poison channel_avg (and therefore every
# cluster bonus + the loser threshold). We exclude these from the learning averages.
_OFF_NICHE_TERMS = (
    "world cup", "golden boot", "ballon d", "champions league", "premier league", "la liga",
    "penalty", "goalkeeper", "free kick", "corner kick", "offside", "hat trick", "hat-trick",
    "clean sheet", "nutmeg", "matchday", "transfer window", "drogba", "messi", "ronaldo",
    "mbappe", "neymar", "footballer", "soccer", "fifa", "uefa", "striker", "midfielder",
)


def _is_off_niche(title: str, topic: str = "") -> bool:
    """True for clearly football/sports-era videos that predate the psychology pivot."""
    t = (str(title) + " " + str(topic)).lower()
    return any(term in t for term in _OFF_NICHE_TERMS)


# Empirical-Bayes prior strength: how many 'channel-average' pseudo-videos to blend into a
# cluster's average. Higher = more shrinkage of small-sample clusters toward the mean.
EB_PRIOR_K = 5.0


def _shrink_to_mean(avg: float, n: int, channel_avg: float, k: float = EB_PRIOR_K) -> float:
    """Empirical-Bayes shrinkage: pull a small-sample cluster average toward the channel mean
    so a single lucky (or unlucky) video can't make a whole cluster look 3x better/worse
    forever. n=1 lands ~5/6 of the way to the mean; large n ~= the raw average."""
    try:
        if channel_avg <= 0 or (n + k) <= 0:
            return avg
        return (avg * n + channel_avg * k) / (n + k)
    except Exception:
        return avg


def parse_entry_datetime(entry) -> datetime.datetime:
    if "publish_at" in entry and entry["publish_at"]:
        try:
            val = entry["publish_at"].replace("Z", "+00:00")
            dt_obj = datetime.datetime.fromisoformat(val)
            if dt_obj.tzinfo is None:
                dt_obj = dt_obj.replace(tzinfo=datetime.timezone.utc)
            return dt_obj
        except Exception:
            pass
    if "date" in entry and entry["date"]:
        try:
            d = datetime.date.fromisoformat(entry["date"])
            return datetime.datetime.combine(d, datetime.time(12, 0, 0), tzinfo=datetime.timezone.utc)
        except Exception:
            pass
    return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

def get_cooldown_clusters(publish_at_str: str | None) -> list[str]:
    """Get list of clusters that are on cooldown for the given publish_at slot.
    A cluster is on cooldown if:
    1. A video of that cluster is scheduled within 24 hours of publish_at.
    2. A video of that cluster is the immediate prior scheduled video chronologically before publish_at.
    """
    if publish_at_str:
        target_dt = datetime.datetime.fromisoformat(publish_at_str.replace("Z", "+00:00"))
    else:
        target_dt = datetime.datetime.now(datetime.timezone.utc)

    cooldowns = set()
    ab_path = "ab_log.json"
    if not os.path.exists(ab_path):
        return []

    try:
        with open(ab_path, encoding="utf-8") as f:
            ab = json.load(f)
    except Exception:
        return []

    # Build chronological list of scheduled/published videos
    history = []
    for vid, entry in ab.items():
        title = entry.get("title", "")
        cluster = entry.get("cluster")
        if not cluster:
            cluster = detect_cluster(title)
        if not cluster:
            continue
        dt_val = parse_entry_datetime(entry)
        history.append((dt_val, cluster))

    # Sort history chronologically
    history.sort(key=lambda x: x[0])

    # 1. 24-hour cooldown rule
    for dt_val, cluster in history:
        diff_sec = abs((target_dt - dt_val).total_seconds())
        if diff_sec < 24 * 3600:
            cooldowns.add(cluster)

    # 2. Immediate prior back-to-back rule
    prior_cluster = None
    prior_dt = None
    for dt_val, cluster in history:
        if dt_val < target_dt:
            if prior_dt is None or dt_val > prior_dt:
                prior_dt = dt_val
                prior_cluster = cluster
    if prior_cluster:
        cooldowns.add(prior_cluster)

    return list(cooldowns)

def init_loser_memory():
    """Create default loser memory file with historical failures if it does not exist."""
    loser_file = "loser_memory.json"
    if not os.path.exists(loser_file):
        default_losers = [
            {
                "title": "Why streetlights are turning purple",
                "views": 4,
                "environment": False,
                "annoyance": 2,
                "visual": 5,
                "universality": 1,
                "hook": "explainer"
            },
            {
                "title": "Why the Golden Boot race is broken",
                "views": 5,
                "environment": False,
                "annoyance": 0,
                "visual": 4,
                "universality": 0,
                "hook": "explainer"
            },
            {
                "title": "Why you should put your phone down",
                "views": 5,
                "environment": False,
                "annoyance": 3,
                "visual": 3,
                "universality": 8,
                "hook": "explainer"
            },
            {
                "title": "Why traffic feels like a trap",
                "views": 6,
                "environment": True,
                "annoyance": 8,
                "visual": 6,
                "universality": 8,
                "hook": "explainer"
            },
            {
                "title": "Why you forget why you entered a room",
                "views": 3,
                "environment": False,
                "annoyance": 6,
                "visual": 2,
                "universality": 10,
                "hook": "explainer"
            },
            {
                "title": "Why your brain tortures you with earworm songs",
                "views": 1,
                "environment": False,
                "annoyance": 5,
                "visual": 1,
                "universality": 9,
                "hook": "explainer"
            }
        ]
        try:
            with open(loser_file, "w", encoding="utf-8") as f:
                json.dump(default_losers, f, indent=2)
        except Exception:
            pass

def init_hook_memory():
    """Create default hook memory file if it does not exist."""
    hook_file = "hook_memory.json"
    if not os.path.exists(hook_file):
        default_hooks = {
            "physical_moment": {
                "videos": 0,
                "avg_views": 0.0,
                "stayed_to_watch": None,
                "avd": None
            },
            "question_hook": {
                "videos": 0,
                "avg_views": 0.0,
                "stayed_to_watch": None,
                "avd": None
            }
        }
        with open(hook_file, "w", encoding="utf-8") as f:
            json.dump(default_hooks, f, indent=2)

def init_memory():
    """Create the default winner memory file with historical stats if it does not exist."""
    if not os.path.exists(MEMORY_FILE):
        default_memory = {
            "channel_avg_views": 534.3,
            "topic_clusters": {
                "airport": {"videos": 3, "avg_views": 1172.3, "best_views": 1600, "recent_views": [1600, 1209, 708]},
                "hotel": {"videos": 2, "avg_views": 1104.0, "best_views": 1357, "recent_views": [1357, 851]},
                "supermarket": {"videos": 1, "avg_views": 1144.0, "best_views": 1144, "recent_views": [1144]},
                "elevator": {"videos": 1, "avg_views": 1074.0, "best_views": 1074, "recent_views": [1074]},
                "traffic": {"videos": 3, "avg_views": 190.0, "best_views": 560, "recent_views": [560, 6, 4]},
                "gas_station": {"videos": 1, "avg_views": 556.0, "best_views": 556, "recent_views": [556]},
                "mall": {"videos": 2, "avg_views": 278.5, "best_views": 540, "recent_views": [540, 17]},
                "restaurant": {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []},
                "airline": {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []},
                "brain": {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []},
                "social": {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []},
                "technology": {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []},
                "money": {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []}
            },
            "last_updated": datetime.datetime.now().isoformat()
        }
        try:
            with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                json.dump(default_memory, f, indent=2)
        except Exception:
            pass
    else:
        # Self-heal / merge new clusters if winner_memory.json already exists
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                memory = json.load(f)
            updated = False
            if "topic_clusters" not in memory:
                memory["topic_clusters"] = {}
                updated = True
            for c in CLUSTERS:
                if c not in memory["topic_clusters"]:
                    memory["topic_clusters"][c] = {"videos": 0, "avg_views": 0.0, "best_views": 0, "recent_views": []}
                    updated = True
            if updated:
                with open(MEMORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(memory, f, indent=2)
        except Exception:
            pass
    init_hook_memory()

def update_memory(cfg: dict, log=print):
    """Fetch view counts for all channel index videos, group by cluster, and save stats."""
    init_memory()
    try:
        import upload
        import boost
        idx = boost._load(boost.INDEX_FILE, [])
        if not idx:
            log("[winner_memory] Index is empty, skipping stats update.")
            return
            
        videos = [v for v in idx if v.get("video_id") and "Weekly" not in v.get("title", "")]
        if not videos:
            log("[winner_memory] No videos found in index.")
            return
            
        ab_log = {}
        if os.path.exists("ab_log.json"):
            try:
                with open("ab_log.json") as f:
                    ab_log = json.load(f)
            except Exception:
                pass

        # Chunk stats fetch from YouTube API
        ids = [v["video_id"] for v in videos]
        stats = {}
        for i in range(0, len(ids), 50):
            chunk = ids[i:i+50]
            try:
                stats.update(upload.video_stats(chunk))
            except Exception as e:
                log(f"[winner_memory] Stats fetch chunk failed: {e}")
                
        if not stats:
            log("[winner_memory] Failed to retrieve stats from API. Retaining cache.")
            return
            
        cluster_data = {c: {
            "views_list": [],
            "best_views": 0,
            "last_win": None,
            "decayed_views": [],
            "decay_weights": [],
            "stayed_to_watch_list": [],
            "avd_list": []
        } for c in CLUSTERS}
        all_views = []
        all_decayed_views = []
        all_decay_weights = []
        
        # Process in reverse chronological order (newest first)
        for v in reversed(videos):
            vid = v["video_id"]
            if vid not in stats:
                continue
            # De-contaminate the learning averages: skip clearly off-niche (football-era) videos
            # so channel_avg + every cluster bonus + the loser threshold reflect the CURRENT
            # psychology niche only, not the pivoted-away football back-catalogue.
            if _is_off_niche(v.get("title", ""), v.get("topic", "")):
                continue
            views = stats[vid].get("viewCount", 0)

            stayed_to_watch = None
            avd = None
            if ab_log and vid in ab_log:
                stayed_to_watch = ab_log[vid].get("stayed_to_watch")
                avd = ab_log[vid].get("avd")

            decay_weight = 1.0
            v_date = v.get("date")
            if v_date:
                try:
                    if "T" in v_date:
                        dt_obj = datetime.datetime.fromisoformat(v_date.replace("Z", "+00:00")).replace(tzinfo=None)
                    else:
                        dt_obj = datetime.datetime.strptime(v_date[:10], "%Y-%m-%d")
                    days_old = (datetime.datetime.now() - dt_obj).days
                    if days_old <= 14:
                        decay_weight = 1.5
                    elif days_old <= 45:
                        decay_weight = 1.0
                    else:
                        decay_weight = 0.5
                except Exception:
                    pass
            
            all_views.append(views)
            all_decayed_views.append(views * decay_weight)
            all_decay_weights.append(decay_weight)
            
            c = detect_cluster(v["title"], v.get("topic", ""))
            if c:
                cluster_data[c]["views_list"].append(views)
                cluster_data[c]["decayed_views"].append(views * decay_weight)
                cluster_data[c]["decay_weights"].append(decay_weight)
                if stayed_to_watch is not None:
                    cluster_data[c]["stayed_to_watch_list"].append(stayed_to_watch)
                if avd is not None:
                    cluster_data[c]["avd_list"].append(avd)
                if views > cluster_data[c]["best_views"]:
                    cluster_data[c]["best_views"] = views
                if v_date:
                    if not cluster_data[c]["last_win"] or v_date > cluster_data[c]["last_win"]:
                        cluster_data[c]["last_win"] = v_date
                        
        channel_avg = sum(all_views) / max(len(all_views), 1)
        decayed_channel_avg = sum(all_decayed_views) / max(sum(all_decay_weights), 1) if sum(all_decay_weights) > 0 else channel_avg
        
        topic_clusters = {}
        for c in CLUSTERS:
            views_list = cluster_data[c]["views_list"]
            c_vids = len(views_list)
            
            weight_sum = sum(cluster_data[c]["decay_weights"])
            if weight_sum > 0:
                c_avg = sum(cluster_data[c]["decayed_views"]) / weight_sum
            else:
                c_avg = sum(views_list) / max(c_vids, 1) if c_vids > 0 else 0.0
                
            avg_st = sum(cluster_data[c]["stayed_to_watch_list"]) / len(cluster_data[c]["stayed_to_watch_list"]) if cluster_data[c]["stayed_to_watch_list"] else None
            avg_av = sum(cluster_data[c]["avd_list"]) / len(cluster_data[c]["avd_list"]) if cluster_data[c]["avd_list"] else None

            topic_clusters[c] = {
                "videos": c_vids,
                "avg_views": round(c_avg, 1),
                "best_views": cluster_data[c]["best_views"],
                "recent_views": views_list,
                "avg_stayed_to_watch": round(avg_st, 1) if avg_st is not None else None,
                "avg_avd": round(avg_av, 1) if avg_av is not None else None
            }
            
        memory = {
            "channel_avg_views": round(decayed_channel_avg, 1),
            "topic_clusters": topic_clusters,
            "last_updated": datetime.datetime.now().isoformat()
        }
        
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, indent=2)
            
        log(f"[winner_memory] Stats refreshed. Channel average views: {channel_avg:.1f}")
        
        # Hook Memory tracking and performance logging
        hook_entries = []
        hook_stats = {}
        for v in reversed(videos):
            vid = v["video_id"]
            if vid not in stats:
                continue
            views = stats[vid].get("viewCount", 0)
            
            # Determine hook_type
            h_type = v.get("hook_type")
            if not h_type:
                t_lower = v.get("title", "").lower()
                if any(w in t_lower for w in ["walk", "sleep", "milk", "pillow", "snack", "elevator", "snooze", "mirror", "room", "door", "button", "grab"]):
                    h_type = "physical_moment"
                else:
                    h_type = "explainer"
            
            hook_entries.append({
                "title": v.get("title", ""),
                "views": views,
                "hook_type": h_type
            })
            
            if h_type not in hook_stats:
                hook_stats[h_type] = []
            hook_stats[h_type].append(views)
            
        try:
            hook_summary = {}
            hook_retentions = {}
            hook_avds = {}
            
            for v in reversed(videos):
                vid = v["video_id"]
                if vid not in stats:
                    continue
                h_type = v.get("hook_type")
                if not h_type:
                    t_lower = v.get("title", "").lower()
                    if any(w in t_lower for w in ["walk", "sleep", "milk", "pillow", "snack", "elevator", "snooze", "mirror", "room", "door", "button", "grab"]):
                        h_type = "physical_moment"
                    else:
                        h_type = "explainer"
                
                key_name = h_type   # use the real hook type (was mislabeled 'explainer'->'question_hook')
                if key_name not in hook_retentions:
                    hook_retentions[key_name] = []
                    hook_avds[key_name] = []
                if ab_log and vid in ab_log:
                    st = ab_log[vid].get("stayed_to_watch")
                    av = ab_log[vid].get("avd")
                    if st is not None:
                        hook_retentions[key_name].append(st)
                    if av is not None:
                        hook_avds[key_name].append(av)

            for h_type, views_list in hook_stats.items():
                h_avg = sum(views_list) / max(len(views_list), 1)
                key_name = h_type   # use the real hook type (was mislabeled 'explainer'->'question_hook')
                
                avg_st = sum(hook_retentions.get(key_name, [])) / len(hook_retentions.get(key_name, [])) if hook_retentions.get(key_name) else None
                avg_av = sum(hook_avds.get(key_name, [])) / len(hook_avds.get(key_name, [])) if hook_avds.get(key_name) else None
                
                hook_summary[key_name] = {
                    "videos": len(views_list),
                    "avg_views": round(h_avg, 1),
                    "stayed_to_watch": round(avg_st, 1) if avg_st is not None else None,
                    "avd": round(avg_av, 1) if avg_av is not None else None
                }
            with open("hook_memory.json", "w", encoding="utf-8") as f:
                json.dump(hook_summary, f, indent=2)
        except Exception as he:
            log(f"[winner_memory] Hook memory write skipped (non-fatal): {he}")
            
        log("\n[hook_performance]")
        for h_type, views_list in hook_stats.items():
            h_avg = sum(views_list) / max(len(views_list), 1)
            log(f"  {h_type}: avg_views={h_avg:.1f} ({len(views_list)} videos)")
            
        # Loser Memory (Failure Dataset) tracking
        init_loser_memory()
        loser_entries = []
        if os.path.exists("loser_memory.json"):
            try:
                with open("loser_memory.json", encoding="utf-8") as lf:
                    loser_entries = json.load(lf)
            except Exception:
                pass
        loser_titles = {le.get("title", "").strip().lower() for le in loser_entries if le.get("title")}
        
        for v in reversed(videos):
            vid = v["video_id"]
            if vid not in stats:
                continue
            # don't record football-era videos as psychology "losers"
            if _is_off_niche(v.get("title", ""), v.get("topic", "")):
                continue
            views = stats[vid].get("viewCount", 0)
            if views < channel_avg * 0.25:
                title = v.get("title", "")
                if title.strip().lower() not in loser_titles:
                    h_type = v.get("hook_type")
                    if not h_type:
                        t_lower = title.lower()
                        if any(w in t_lower for w in ["walk", "sleep", "milk", "pillow", "snack", "elevator", "snooze", "mirror", "room", "door", "button", "grab"]):
                            h_type = "physical_moment"
                        else:
                            h_type = "explainer"
                    env_score = v.get("environment_score", 0)
                    is_env = env_score >= 8 or bool(v.get("environment_bonus", 0))
                    loser_entries.append({
                        "title": title,
                        "views": views,
                        "environment": is_env,
                        "annoyance": v.get("annoyance_score", 0),
                        "visual": v.get("visual_score", 0),
                        "universality": v.get("universality_score", 0),
                        "hook_type": h_type,
                        "cluster": detect_cluster(title),
                        "quality_score": v.get("quality_score", 0)
                    })
                    loser_titles.add(title.strip().lower())
        try:
            with open("loser_memory.json", "w", encoding="utf-8") as f:
                json.dump(loser_entries, f, indent=2)
            log(f"[winner_memory] Failure dataset updated. Total losers tracked: {len(loser_entries)}")
        except Exception as le_err:
            log(f"[winner_memory] Loser memory write failed (non-fatal): {le_err}")
            
    except Exception as e:
        log(f"[winner_memory] Error updating stats: {e}")

def get_winner_bonus(topic: str) -> tuple[str | None, float]:
    """Calculate the winner bonus for a topic: min(cluster_avg / channel_avg, 2.0)."""
    init_memory()
    try:
        if not os.path.exists(MEMORY_FILE):
            return None, 0.0
        with open(MEMORY_FILE, encoding="utf-8") as f:
            mem = json.load(f)
            
        channel_avg = mem.get("channel_avg_views", 0.0)
        if channel_avg <= 0:
            return None, 0.0
            
        c = detect_cluster(topic)
        if not c:
            return None, 0.0
            
        cl = mem.get("topic_clusters", {}).get(c, {})
        # empirical-Bayes shrinkage so small-sample clusters don't dictate the bonus
        cluster_avg = _shrink_to_mean(cl.get("avg_views", 0.0), cl.get("videos", 0) or 0, channel_avg)
        bonus = min(cluster_avg / channel_avg, 2.0)
        return c, round(bonus, 2)
    except Exception:
        return None, 0.0


def get_loser_titles(limit: int = 40) -> list:
    """Return recent flopped video titles (below-average performers) so the generator can
    actively AVOID re-proposing them. Previously loser_memory.json was write-only - recorded
    every flop but never read by topic selection."""
    try:
        if not os.path.exists("loser_memory.json"):
            return []
        with open("loser_memory.json", encoding="utf-8") as f:
            losers = json.load(f)
        titles = [str(le.get("title", "")).strip() for le in losers
                  if isinstance(le, dict) and le.get("title")]
        return titles[-limit:]   # most recent are appended last
    except Exception:
        return []


def _load_retention_memory() -> dict:
    """Load analytics_memory.json cluster retention data (stayed-to-watch + AVD).
    Returns {} on any failure so callers degrade gracefully to views-only."""
    try:
        if os.path.exists("analytics_memory.json"):
            with open("analytics_memory.json", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def get_cluster_strengths() -> dict[str, float]:
    """Returns cluster -> strength score (0-10) blending VIEWS with RETENTION.

    Why blended: raw views are a vanity metric on Shorts (the feed inflates them and
    they don't predict whether YouTube keeps pushing you). RETENTION (stayed-to-watch %
    and average view duration) is the real currency. But retention data is sparse early
    on, so we trust it MORE as the sample grows: with few videos in a cluster we lean on
    views; with many, retention dominates. This is the feedback loop that was previously
    collected (analytics_memory.json) but never used in selection.
    """
    init_memory()
    strengths = {c: 5.0 for c in CLUSTERS}
    try:
        if not os.path.exists(MEMORY_FILE):
            return strengths
        with open(MEMORY_FILE, encoding="utf-8") as f:
            mem = json.load(f)
        channel_avg = mem.get("channel_avg_views", 0.0)
        clusters_info = mem.get("topic_clusters", {})

        ret_mem = _load_retention_memory()
        ret_clusters = ret_mem.get("clusters", {})

        # Channel-wide retention baselines, to normalize each cluster against.
        all_stayed = [c.get("avg_stayed_to_watch") for c in ret_clusters.values()
                      if c.get("avg_stayed_to_watch") is not None]
        all_avd = [c.get("avg_avd") for c in ret_clusters.values()
                   if c.get("avg_avd") is not None]
        base_stayed = (sum(all_stayed) / len(all_stayed)) if all_stayed else None
        base_avd = (sum(all_avd) / len(all_avd)) if all_avd else None

        for c in CLUSTERS:
            # --- views component (0-10), normalized so channel-average == 5.0 ---
            views_score = 5.0
            if channel_avg > 0:
                ci = clusters_info.get(c, {})
                # shrink the cluster average toward the channel mean by sample size so a single
                # lucky/unlucky video can't make a whole cluster look 3x better/worse forever.
                avg = _shrink_to_mean(ci.get("avg_views", 0.0), ci.get("videos", 0) or 0, channel_avg)
                views_score = min((avg / channel_avg) * 5.0, 10.0)

            # --- retention component (0-10), from stayed-to-watch and AVD ---
            rc = ret_clusters.get(c, {})
            n = rc.get("count", 0) or 0
            stayed = rc.get("avg_stayed_to_watch")
            avd = rc.get("avg_avd")
            ret_score = None
            parts = []
            if stayed is not None and base_stayed:
                parts.append(min((stayed / base_stayed) * 5.0, 10.0))
            if avd is not None and base_avd:
                parts.append(min((avd / base_avd) * 5.0, 10.0))
            if parts:
                ret_score = sum(parts) / len(parts)

            # --- blend: retention weight grows with sample size ---
            # n=0 -> 0% retention; n>=5 -> ~70% retention. Caps so one cluster with a
            # huge sample can't fully ignore views.
            if ret_score is not None and n > 0:
                ret_weight = min(0.70, 0.14 * n)   # 1->0.14, 5->0.70, capped
                score = views_score * (1 - ret_weight) + ret_score * ret_weight
            else:
                score = views_score
            strengths[c] = round(score, 1)
    except Exception:
        pass
    return strengths

def log_winner_stats(log=print):
    """Print the cluster rollings and winner bonuses for the generation cycle."""
    init_memory()
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            mem = json.load(f)
            
        channel_avg = mem.get("channel_avg_views", 0.0)
        clusters_info = mem.get("topic_clusters", {})
        
        # Sort by avg views descending
        sorted_clusters = sorted(CLUSTERS, key=lambda c: clusters_info.get(c, {}).get("avg_views", 0.0), reverse=True)
        
        for c in sorted_clusters:
            avg = clusters_info.get(c, {}).get("avg_views", 0.0)
            log(f"[cluster] {c} avg={avg:.0f} views")
            
        log("") # empty line
        
        log("[winner_bonus]")
        for c in sorted_clusters:
            avg = clusters_info.get(c, {}).get("avg_views", 0.0)
            bonus = min(avg / channel_avg, 2.0) if channel_avg > 0 else 0.0
            log(f"{c} +{bonus:.1f}")
            
    except Exception as e:
        log(f"[winner_memory] Error logging statistics: {e}")

def update_hook_library(title: str, hook_text: str, hook_type: str, hook_structure: str, first_frame_description: str, visual_thesis: str, views: int = 0, stayed_to_watch: float | None = None, avd: float | None = None):
    """Add or update an entry in hook_library.json"""
    hook_file = "hook_library.json"
    library = []
    if os.path.exists(hook_file):
        try:
            with open(hook_file, encoding="utf-8") as f:
                library = json.load(f)
        except Exception:
            pass
            
    for entry in library:
        if entry.get("title") == title:
            entry["views"] = views
            entry["stayed_to_watch"] = stayed_to_watch
            entry["average_view_duration"] = avd
            break
    else:
        library.append({
            "title": title,
            "hook_text": hook_text,
            "hook_type": hook_type,
            "hook_structure": hook_structure,
            "first_frame_description": first_frame_description,
            "visual_thesis": visual_thesis,
            "views": views,
            "stayed_to_watch": stayed_to_watch,
            "average_view_duration": avd
        })
        
    try:
        with open(hook_file, "w", encoding="utf-8") as f:
            json.dump(library, f, indent=2)
    except Exception as e:
        print(f"[winner_memory] Failed to update hook library: {e}")
