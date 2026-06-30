"""
trend_seeds.py - DISCOVER evergreen, relatable everyday topics.

This replaces the old "news/RSS" scraper with a curated pool of S-Tier
and Tier-2 universal human experiences. The goal is to surface topics
that make the viewer instantly think: "WAIT... THAT HAPPENS TO ME."
"""
import random

# Tier 1 Topics (Best) - Everyone experiences these
_TIER_1 = [
    "airports",
    "supermarkets",
    "smartphones",
    "apps and notifications",
    "restaurants and menus",
    "traffic and driving",
    "elevators",
    "hotels",
    "shopping and malls",
    "social media feeds",
    "online stores and checkout",
    "pricing and sales",
]

# Tier 2 Topics - Many experience these
_TIER_2 = [
    "clothing and fashion sizing",
    "home appliances",
    "offices and cubicles",
    "schools and classrooms",
    "fast food drive-thrus",
    "movie theaters",
    "gas stations",
    "gyms and fitness centers",
]

def trending_seeds(max_seeds: int = 6, tournament_state: dict | None = None) -> list[str]:
    """Return up to `max_seeds` highly relatable everyday categories to use as
    script seeds. Mixes heavily from Tier 1 with a few Tier 2s."""
    
    # We heavily weight Tier 1 over Tier 2 to ensure maximum relatability
    pool = _TIER_1 * 3 + _TIER_2
    
    # Shuffle and pick max_seeds distinct categories
    random.shuffle(pool)
    
    out = []
    seen = set()
    for s in pool:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= max_seeds:
            break
            
    return out

if __name__ == "__main__":
    # quick manual test
    print("Seed categories for today:")
    for s in trending_seeds():
        print(" -", s)
