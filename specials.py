"""
specials.py - Two daily special slots:
  SYSTEM TOUR: one major everyday system per day, in order.
  TRENDING: one video riding today's biggest viral design/psychology story (Claude web search).
Both are once-per-day idempotent.
"""
import datetime as dt
import json
import os
import shutil
import subprocess

TOUR_FILE = "system_tour.json"
TREND_FILE = "trending_done.json"

TEAMS = [
    "Airports", "Supermarkets", "Casinos", "Hospitals", "Shopping Malls",
    "Theme Parks", "Fast Food Drive-thrus", "Movie Theaters", "Elevators",
    "Smartphones", "Social Media Feeds", "Dating Apps", "Highways",
    "Subway Systems", "Office Layouts", "Hotel Rooms", "Coffee Shops"
]


def _today() -> str:
    return dt.date.today().isoformat()


def _load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def _save(path, d):
    with open(path, "w") as f:
        json.dump(d, f, indent=2)


# ---------------------------------------------------------------- team tour
def team_tour_topic() -> str | None:
    """One system per day, marked done at handout."""
    state = _load(TOUR_FILE, {"index": 0, "last_date": ""})
    if state["last_date"] == _today():
        return None
    if state["index"] >= len(TEAMS):
        return None  # tour complete
    team = TEAMS[state["index"]]
    stop = state["index"] + 1
    _save(TOUR_FILE, {"index": stop, "last_date": _today()})
    return (f"SYSTEM TOUR stop {stop} of {len(TEAMS)}: {team}. "
            f"Reveal the single most surprising hidden trick or psychological manipulation "
            f"used in {team}. Title must start with '{team}:'. End by asking viewers to comment "
            f"which everyday system the tour should visit tomorrow.")


# ---------------------------------------------------------------- trending
def _claude_search(prompt: str) -> dict | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, "-p", prompt, "--allowedTools", "WebSearch",
                               "--output-format", "json"],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8", errors="replace")
        result = json.loads(proc.stdout).get("result", "")
        i, j = result.find("{"), result.rfind("}")
        return json.loads(result[i:j + 1])
    except Exception:
        return None


def trending_match_and_player(cfg: dict) -> dict | None:
    """Targeted web search for TODAY'S most talked-about design flaw or tech manipulation."""
    if cfg.get("llm_provider") != "claude_code":
        return None
    prompt = (
        f"You are finding what people are buzzing about RIGHT NOW, today {_today()}. "
        f"Search the web (tech news, design blogs, viral social media trends) and identify ONE thing:\n"
        f"The single most talked-about everyday system, brand, or app today (e.g. a controversial "
        f"new feature, a viral revelation about how a store works, a dark pattern exposed).\n"
        f"Give the surprising angle a viral Shorts channel should take.\n"
        'Respond ONLY with JSON: {"player": {"name": "...", "why": '
        '"why it is trending today", "angle": "..."}} '
        'Use null if there is genuinely nothing notable today.'
    )
    return _claude_search(prompt)


def trending_topic(cfg: dict) -> str | None:
    """Today's hottest subject as ONE video."""
    done = _load(TREND_FILE, {})
    if done.get(_today()):
        return None
    data = trending_match_and_player(cfg)
    if not data:
        return None
    player = data.get("player") or {}
    if player.get("name"):
        _save(TREND_FILE, {**done, _today(): f"subject:{player['name']}"})
        return (f"TRENDING TODAY: {player['name']} is highly talked-about right now "
                f"({player.get('why','')}). Angle: {player.get('angle','')} "
                f"Make it feel urgent and current. Title starts with {player['name']}.")
    return None
