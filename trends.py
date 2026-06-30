"""
trends.py - How hot is a player/team right now? Free Google Trends data
(pytrends). Used to (a) steer topic selection toward trending subjects and
(b) give trending scripts a quality-gate bonus.
Fully non-fatal: any failure returns neutral scores and the pipeline proceeds.
Install once: pip install pytrends
"""
import re

_cache: dict = {}
DEFAULT_WINDOW = "now 1-d"  # last 24h: the live football news cycle


def search_term(seed: str) -> str:
    """Turn a topic seed into a clean trends search term."""
    s = seed
    s = re.sub(r"\bthe\b", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    words = s.split()
    if len(words) > 4:
        s = " ".join(words[:4])
    return s


def scores(terms: list[str], window: str = DEFAULT_WINDOW) -> dict:
    """Return {term: 0-100 trend score}. Batched (5 per request), cached per run."""
    out = {}
    missing = []
    for t in terms:
        key = (t, window)
        if key in _cache:
            out[t] = _cache[key]
        else:
            missing.append(t)
    if missing:
        try:
            from pytrends.request import TrendReq
            py = TrendReq(hl="en-US", tz=0, timeout=(5, 15))
            for i in range(0, len(missing), 5):
                batch = missing[i:i + 5]
                try:
                    py.build_payload(batch, timeframe=window)
                    df = py.interest_over_time()
                    for t in batch:
                        val = float(df[t].mean()) if (df is not None and t in df) else 0.0
                        _cache[(t, window)] = val
                        out[t] = val
                except Exception:
                    for t in batch:
                        _cache[(t, window)] = 0.0
                        out[t] = 0.0
        except Exception:
            for t in missing:
                out[t] = 0.0
    return out


def seed_score(seed: str, window: str = DEFAULT_WINDOW) -> float:
    return scores([search_term(seed)], window).get(search_term(seed), 0.0)
