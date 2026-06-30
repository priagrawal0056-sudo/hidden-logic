"""
trend_bridge.py - turn LIVE cultural moments into Hidden Logic seeds.

The channel's rule: sports/trends ONLY work when tied to UNIVERSAL psychology, never
gossip/drama/results. This module detects when something is genuinely hot right now
(an F1 race weekend, a World Cup / Euros window, a big product launch) and emits
channel-safe SEED topics that ride that attention through a psychology/design angle.

It is a SEED SOURCE, not a topic override: whatever it returns still flows through the
normal candidate pool and every quality gate. If nothing is hot, it returns [] and the
pipeline behaves exactly as before. Fully non-fatal.

Two detection layers:
  1. CALENDAR: recurring events we can know without a network call (F1 weekends by month
     cadence, summer-tournament windows). Cheap and reliable.
  2. INTEREST (optional): if pytrends is available, confirm a candidate subject is actually
     spiking before we lean into it, so we don't post F1 content on a dead week.

Every emitted seed is phrased as an EVERYDAY-PSYCHOLOGY angle, e.g. not "Verstappen wins"
but "why you always lose to teams in red" / "why turn one decides the whole race".
"""
import datetime as dt

# Channel-safe angles for big sporting moments. Each is a (subject, seed) pair where the
# seed is already a Hidden-Logic-style everyday-psychology prompt, NOT a result/gossip take.
_F1_SEEDS = [
    "why your brain thinks the car in front is slower than it is",
    "why first corner crashes happen on every race start",
    "why drivers in red cars feel faster to you",
    "why you can't look away from a crash replay",
    "why the leader almost never gets overtaken on the last lap",
]
# Football is weighted HEAVIER: this channel's actual audience overlaps with football
# fans (their other subscriptions are football channels), so football-psychology angles
# are audience-aligned, not a gimmick. Bigger pool = more variety when it's live.
_FOOTBALL_SEEDS = [
    "why you always lose to teams wearing red",
    "why penalty takers look the wrong way on purpose",
    "why home crowds actually change the score",
    "why injury time feels longer than it is",
    "why a last-minute goal feels better than an early one",
    "why you instantly trust a team in their home kit",
    "why the goalkeeper almost always dives the wrong way",
    "why a 1-0 lead is the most dangerous scoreline",
    "why fans blame the referee even when they're wrong",
    "why the underdog feels more exciting to watch",
]
_OLYMPICS_SEEDS = [
    "why you tense up watching someone balance",
    "why sprinters in the outer lanes feel slower",
    "why a photo finish fools your eyes",
    "why you hold your breath during a high dive",
]

# Subjects we'll check for real interest (used to confirm calendar guesses).
_SUBJECT_TERMS = {
    "f1": "formula 1",
    "football": "football",
    "olympics": "olympics",
}


def _month(today: dt.date) -> int:
    return today.month


def _calendar_candidates(today: dt.date) -> list[str]:
    """Cheap, no-network guess of what's culturally live based on the date.
    Football is listed FIRST (highest priority) because it's this channel's core
    audience overlap and club football runs almost year-round."""
    m = today.month
    cands = []
    # Football: club seasons run Aug-May across major leagues, summer tournaments Jun-Jul.
    # That's essentially all year, so football is almost always an eligible angle.
    cands.append("football")
    # F1 season runs roughly March-December with most months having a race weekend.
    if 3 <= m <= 12:
        cands.append("f1")
    # Summer Olympics windows (late July - August) in their years; cheap heuristic only.
    if m in (7, 8):
        cands.append("olympics")
    return cands


def _confirm_interest(subject: str) -> bool:
    """Optional pytrends confirmation that the subject is actually spiking now.
    Returns True if hot OR if trends is unavailable (fail-open so calendar still works)."""
    term = _SUBJECT_TERMS.get(subject)
    if not term:
        return True
    try:
        import trends
        heat = trends.scores([term], window="now 7-d").get(term, 0.0)
        # 40/100 over the last week is a reasonable "this is live" bar.
        return heat >= 40.0
    except Exception:
        return True  # no trends lib -> don't block the calendar signal


def trending_seeds(max_seeds: int = 2, confirm: bool = True) -> list[str]:
    """Return up to max_seeds channel-safe seeds tied to a genuinely live moment, or []
    if nothing is hot. confirm=True checks real interest via pytrends when available."""
    today = dt.date.today()
    out = []
    seen_subjects = set()
    for subject in _calendar_candidates(today):
        if subject in seen_subjects:
            continue
        if confirm and not _confirm_interest(subject):
            continue
        pool = {"f1": _F1_SEEDS, "football": _FOOTBALL_SEEDS,
                "olympics": _OLYMPICS_SEEDS}.get(subject, [])
        if not pool:
            continue
        import random
        out.append(random.choice(pool))
        seen_subjects.add(subject)
        if len(out) >= max_seeds:
            break
    return out


def is_trend_seed(seed: str) -> bool:
    """True if a seed string came from this bridge (used to apply a freshness boost)."""
    allp = _F1_SEEDS + _FOOTBALL_SEEDS + _OLYMPICS_SEEDS
    return seed in allp


if __name__ == "__main__":
    print("Live trend seeds today:", trending_seeds(confirm=False))
