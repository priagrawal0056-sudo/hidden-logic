"""
morning_brief.py - your daily Hidden Logic command center.

Runs Steps 1-4 of the daily workflow automatically and prints a briefing so you spend
your morning CHOOSING, not gathering:

  Step 1  What's trending right now (live events the channel can ride)
  Step 2  How recent uploads performed (the analytics feedback signal)
  Step 3  20 candidate ideas drawn from the real seed pools + trends
  Step 4  Each scored on the 6-criterion rubric, bucketed into S / A / B tiers

Then you pick the single highest-potential idea and run:
    python run_daily.py --topic "Your Chosen Title"

This does NOT generate or upload anything. It's read-only: it reads the same memory
files the pipeline writes (winner_memory.json, analytics_memory.json, channel_index.json)
so the briefing reflects the channel's actual learned performance. Fully non-fatal -
any missing data degrades gracefully.

Usage:
    python morning_brief.py            # full briefing, 20 ideas
    python morning_brief.py --n 30     # more ideas
    python morning_brief.py --pillar food   # bias ideas toward one pillar
"""
import argparse
import datetime as dt
import json
import os
import random

# ----- the 6-criterion rubric from the daily workflow (each /10, film 50+/60) -----
RUBRIC = ["everyone_experienced", "curiosity", "psychology", "shareability", "evergreen", "fits_brand"]

# Pillars -> the clusters/seed-families that belong to each (for the --pillar filter and labeling).
PILLARS = {
    "brain":    ["memory", "attention", "perception", "social", "emotions", "cognitive_bias", "decision_making"],
    "food":     ["restaurant", "fast_food", "supermarket", "buffet"],
    "airport":  ["airport", "airline", "tsa"],
    "shopping": ["mall", "retail_layout", "supermarket", "pricing"],
    "design":   ["hotel", "casino", "elevator", "escalator", "gas_station"],
    "sports":   ["football", "f1", "olympics"],
}


def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def step1_trends():
    """What's live right now that the channel can ride."""
    out = []
    try:
        import trend_bridge
        live = trend_bridge.trending_seeds(confirm=False, max_seeds=4)
        for s in live:
            out.append(s)
    except Exception:
        pass
    return out


def step2_analytics():
    """Recent performance signal: cluster strengths (retention-blended) + analyzer brief."""
    info = {"top_clusters": [], "weak_clusters": [], "brief": None, "channel_avg": None}
    try:
        import winner_memory
        strengths = winner_memory.get_cluster_strengths()
        ranked = sorted(strengths.items(), key=lambda x: -x[1])
        info["top_clusters"] = ranked[:5]
        info["weak_clusters"] = [r for r in ranked if r[1] < 4.0][:5]
    except Exception:
        pass
    wm = _load_json("winner_memory.json", {})
    info["channel_avg"] = wm.get("channel_avg_views")
    info["brief"] = _load_json("content_brief.json", None)
    return info


def _candidate_pool(n, pillar=None):
    """Build candidate ideas from the real seed pools + live trends."""
    cands = []
    # live trend seeds first (timely, high-upside)
    for s in step1_trends():
        cands.append(("trend", s))
    try:
        import scriptgen, winner_memory
        seeds = list(scriptgen.SEEDS)
        # add adjacent seeds from strong clusters
        for c, adj in winner_memory.ADJACENT_SEEDS.items():
            seeds.extend(adj)
        # pillar filter
        if pillar and pillar in PILLARS:
            fams = PILLARS[pillar]
            seeds = [s for s in seeds
                     if any(f in (winner_memory.detect_cluster(s) or "") or f in s.lower() for f in fams)]
        random.shuffle(seeds)
        seen = {c[1] for c in cands}
        for s in seeds:
            if s not in seen:
                cands.append(("evergreen", s))
                seen.add(s)
            if len(cands) >= n:
                break
    except Exception:
        pass
    return cands[:n]


def _title_from_seed(seed):
    """Turn a seed into a plain 'Why ...' title (the channel's winning form). The seed is a
    noun/gerund phrase; the actual scriptgen step will polish wording, this is just a label."""
    s = seed.strip()
    if not s:
        return s
    if s.lower().startswith(("why ", "how ", "the reason")):
        return s[0].upper() + s[1:]
    return "Why " + s[0].upper() + s[1:]


def _score(kind, seed, strengths):
    """Score a candidate on the 6-criterion rubric (each /10) using real signals."""
    import winner_memory
    cl = None
    try:
        cl = winner_memory.detect_cluster(seed)
    except Exception:
        cl = None
    cluster_strength = strengths.get(cl, 5.0) if cl else 5.0

    text = seed.lower()
    # everyone_experienced: short, everyday, "you"-centered seeds score high
    everyday_words = ("you", "your", "phone", "drink", "queue", "line", "store", "car",
                      "airport", "hotel", "menu", "price", "mcdonald", "supermarket", "elevator")
    everyone = 6 + 2 * sum(1 for w in everyday_words if w in text)
    everyone = min(everyone, 10)
    # curiosity: contradiction/"always"/"never" cues score high
    curiosity = 6 + (2 if any(w in text for w in ("always", "never", "secret", "wrong", "broken", "actually")) else 0) + random.randint(0, 2)
    curiosity = min(curiosity, 10)
    # psychology: brain/perception/behavior seeds score high
    psych = 9 if (cl in ("memory", "attention", "perception", "social", "emotions", "cognitive_bias")
                  or any(w in text for w in ("brain", "feel", "forget", "remember", "trick"))) else 6
    # shareability: tracks curiosity + everyone
    share = min(round((curiosity + everyone) / 2), 10)
    # evergreen: trend seeds are NOT evergreen; everyday seeds are
    evergreen = 4 if kind == "trend" else 9
    # fits_brand: cluster strength is the proxy (retention-blended performance)
    fits = min(round(cluster_strength), 10)

    scores = {
        "everyone_experienced": everyone,
        "curiosity": curiosity,
        "psychology": psych,
        "shareability": share,
        "evergreen": evergreen,
        "fits_brand": fits,
    }
    total = sum(scores.values())
    return total, scores


def _tier(total, kind):
    """Bucket into S / A / B. Trend ideas get a timing boost - capitalizing on a live event
    (World Cup, race weekend) is high-upside even if the evergreen score is lower."""
    boost = 6 if kind == "trend" else 0
    t = total + boost
    if t >= 48:
        return "S"
    if t >= 40:
        return "A"
    return "B"


def pick_trend_hero():
    """For autopilot: return a topic ONLY if something is genuinely live right now (a World
    Cup match, a race weekend, etc.) that the normal pool selector cannot know about.
    Returns a clean title string, or None to mean "let the smart pool pick instead."

    Rationale: the pool's LLM topic-filter makes excellent evergreen choices on its own;
    the only edge the brief adds is catching a TIMELY trend. So we only override video #1
    when there's a live event worth riding - otherwise we defer to the pool entirely.
    """
    try:
        live = step1_trends()  # live trend seeds from trend_bridge (already confirmed-hot)
        if not live:
            return None
        try:
            import winner_memory
            strengths = winner_memory.get_cluster_strengths()
        except Exception:
            strengths = {}
        best_seed, best_eff = None, -1
        for seed in live:
            total, _ = _score("trend", seed, strengths)
            eff = total + 6  # trend timing boost
            if eff > best_eff:
                best_seed, best_eff = seed, eff
        if best_seed:
            return _title_from_seed(best_seed)
    except Exception:
        pass
    return None


def build_brief(n=20, pillar=None):
    lines = []
    today = dt.date.today().strftime("%A, %B %d, %Y")
    lines.append("=" * 64)
    lines.append(f"  HIDDEN LOGIC - MORNING BRIEF  ({today})")
    lines.append("=" * 64)

    # Step 1
    trends = step1_trends()
    lines.append("\n[1] TRENDING NOW (ride these while they're hot):")
    if trends:
        for t in trends:
            lines.append(f"    * {t}")
    else:
        lines.append("    (nothing strongly live - go evergreen today)")

    # Step 2
    a = step2_analytics()
    lines.append("\n[2] WHAT'S WORKING (retention-blended cluster strength):")
    if a["channel_avg"]:
        lines.append(f"    channel avg views: {a['channel_avg']:.0f}")
    if a["top_clusters"]:
        lines.append("    strongest pillars: " + ", ".join(f"{c}({v:.1f})" for c, v in a["top_clusters"]))
    if a["weak_clusters"]:
        lines.append("    avoid/refresh: " + ", ".join(f"{c}({v:.1f})" for c, v in a["weak_clusters"]))
    if a["brief"]:
        bf = a["brief"]
        if bf.get("best_hooks"):
            lines.append(f"    hooks retaining best: {', '.join(bf['best_hooks'])}")
        if bf.get("hot_subjects"):
            lines.append(f"    hot subjects: {', '.join(bf['hot_subjects'][:3])}")

    # Steps 3 + 4
    try:
        import winner_memory
        strengths = winner_memory.get_cluster_strengths()
    except Exception:
        strengths = {}
    pool = _candidate_pool(n, pillar)
    scored = []
    for kind, seed in pool:
        total, sc = _score(kind, seed, strengths)
        eff = total + (6 if kind == "trend" else 0)   # effective score includes timing boost
        scored.append((_tier(total, kind), total, eff, kind, _title_from_seed(seed), sc))
    # sort: S first, then by EFFECTIVE score (so boosted trends rank within their tier)
    order = {"S": 0, "A": 1, "B": 2}
    scored.sort(key=lambda x: (order[x[0]], -x[2]))

    lines.append(f"\n[3+4] {len(scored)} SCORED IDEAS (rubric /60 - film 50+):")
    cur_tier = None
    tier_label = {"S": "S TIER - post immediately (100k+ potential)",
                  "A": "A TIER - solid evergreen (10k-50k)",
                  "B": "B TIER - only if nothing better"}
    for tier, total, eff, kind, title, sc in scored:
        if tier != cur_tier:
            cur_tier = tier
            lines.append(f"\n  {tier_label[tier]}")
        tag = " [TREND]" if kind == "trend" else ""
        shown = eff if kind == "trend" else total
        lines.append(f"    {shown}/60{tag}  {title}")

    # the single best pick
    if scored:
        best = scored[0]
        lines.append("\n" + "=" * 64)
        lines.append("  TODAY'S TOP PICK:")
        lines.append(f'    {best[4]}  ({best[2]}/60, {best[0]} tier)')
        lines.append("  Run it with:")
        lines.append(f'    python run_daily.py --topic "{best[4]}"')
        lines.append("=" * 64)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="how many ideas to score")
    ap.add_argument("--pillar", type=str, default=None,
                    help="bias ideas to one pillar: brain/food/airport/shopping/design/sports")
    args = ap.parse_args()
    print(build_brief(n=args.n, pillar=args.pillar))


if __name__ == "__main__":
    main()
