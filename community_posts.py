"""
community_posts.py - generate ready-to-paste YouTube Community post text (in the Hidden Logic
voice) for manual posting.

WHY MANUAL: YouTube's Data API does NOT support creating Community posts - there is no
endpoint for it, for anyone. So this tool does the hard part (writing engaging, on-brand
posts tied to everyday design logic) and you paste them into the Community tab yourself, which
takes a few seconds. Community posts drive engagement and reach between video uploads and
keep your subscribers warm.

It produces three kinds of post, all in the calm, curious Hidden Logic voice:
  - POLLS: opinion polls about design quirks, everyday frustrations, and systems. Paste as a YouTube poll.
  - OBSERVATIONS: fascinating observations about how everyday objects/spaces are designed to change your behavior.
  - PROVOCATIVE TAKES: bold design/system opinions that get people talking in the comments.

Usage:
    python community_posts.py            # a balanced batch (polls + observations + takes)
    python community_posts.py --n 8      # more posts
    python community_posts.py --polls-only

Output prints to the console (copy what you want). Add --save to also write a dated text
file you can open later.
"""
import argparse
import datetime as dt
import json
import os
import random


def _load_cfg():
    if not os.path.exists("config.json"):
        raise SystemExit("config.json not found - run from the footy-shorts folder.")
    return json.load(open("config.json", encoding="utf-8"))


# opinion polls about everyday systems (always available)
_OPINION_POLLS = [
    {
        "text": "Which design trick is the most annoying?",
        "options": [
            "No clocks or windows in casinos",
            "Supermarket dairy aisle in the far back",
            "Hotel keycards turning off lights",
            "Fake elevator close-door buttons"
        ]
    },
    {
        "text": "Which everyday frustration has the most baffling design?",
        "options": [
            "Printer ink pricing models",
            "Ticketmaster checkout timers",
            "Streaming app autoplay defaults",
            "Self-checkout weight-checking scales"
        ]
    },
    {
        "text": "The doorway effect (forgetting why you entered a room): design flaw or brain glitch?",
        "options": [
            "Definitely a brain glitch",
            "Poor architectural layout",
            "A system reload moment"
        ]
    },
    {
        "text": "What is the most genius piece of everyday design?",
        "options": [
            "The shopping cart wheel lock",
            "Escalator side safety brushes",
            "Subway station layout and flow",
            "Traffic roundabout efficiency"
        ]
    },
]

# LLM prompt for batch-generating Hidden Logic community posts
_POST_PROMPT = """You run a YouTube channel called Hidden Logic. Your brand is a calm, curious, \
slightly witty documentary creator who exposes the psychological systems and quirks behind everyday frustrations and behaviors \
(Think: Vox, Johnny Harris). Write {n} short YouTube Community posts designed to start discussions in the comments. {kind_rule}

Rules:
- Each post is ONE or TWO sentences, insightful, curious, and engaging.
- Do NOT use banned words: "Hidden", "Secret", "Dark Design", "Manipulation", "Simulation", "Matrix", "Brainwashing", "Control", or "Conspiracy".
- End each by asking a question or daring people to share their experience.
- No hashtags. At most one emoji per post if it fits.

Respond with ONLY a JSON array of strings, each string one post. Example: \
["post one here", "post two here"]"""


def _llm_posts(cfg, n, kind):
    """Generate n observations or provocative takes via the LLM (best-effort)."""
    api_key = cfg.get("gemini_api_key", "")
    if not api_key:
        return []
    kind_rule = {
        "observation": "Make every one an OBSERVATION: a fascinating observation about how an everyday space or object is designed to change your behavior.",
        "provocative_take": "Make every one a PROVOCATIVE TAKE: a bold, slightly contrary opinion about an everyday design or technology that is universally hated or loved, asking viewers if they agree.",
    }.get(kind, "Mix fascinating observations and design contrarian takes.")
    import scriptgen
    prompt = _POST_PROMPT.format(n=n, kind_rule=kind_rule)
    try:
        data = scriptgen._call(api_key, prompt, temperature=1.0)
        # the provider returns JSON; accept a list, or a dict wrapping a list
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = next((v for v in data.values() if isinstance(v, list)), [])
            if not items:
                items = [v for v in data.values() if isinstance(v, str)]
        else:
            items = []
        out = []
        for it in items:
            s = (it if isinstance(it, str) else str(it)).strip().strip('"')
            if s:
                out.append({"kind": kind.upper().replace("_", " "), "text": s})
        return out
    except Exception:
        return []


def generate(cfg, n=6, polls_only=False, takes_only=False):
    """Return a mixed batch of community posts."""
    posts = []

    if not takes_only:
        # opinion polls
        for op in random.sample(_OPINION_POLLS, len(_OPINION_POLLS)):
            posts.append({"kind": "POLL", "text": op["text"], "options": op["options"]})

    if not polls_only:
        # split budget between observations and provocative takes
        n_obs = max(2, n // 2)
        n_take = max(1, n - n_obs)
        posts += _llm_posts(cfg, n_obs, "observation")
        posts += _llm_posts(cfg, n_take, "provocative_take")
        # fallback if the LLM gave nothing, so the tool is never empty
        if not any(p["kind"] in ("OBSERVATION", "PROVOCATIVE TAKE") for p in posts):
            posts += [
                {"kind": "OBSERVATION", "text": "Ever wonder why the milk is always in the absolute back of the supermarket? It's not logistics; it's a path designed to make you walk past everything else first. What's the most annoying store layout you've seen?"},
                {"kind": "PROVOCATIVE TAKE", "text": "Self-checkout machines aren't designed to save you time. They're designed to shift labor costs to the customer, but we still use them because we'd rather deal with a screen than make small talk. Agree or disagree?"},
            ]

    # trim polls so the batch isn't all polls; keep a healthy mix
    poll_posts = [p for p in posts if p["kind"] == "POLL"][: max(3, n // 2)]
    other_posts = [p for p in posts if p["kind"] != "POLL"][:n]
    return poll_posts + other_posts


def _format(posts) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("  MIND GLITCH COMMUNITY POSTS - paste these into your Community tab")
    lines.append("  (YouTube's API can't post these, so copy/paste manually)")
    lines.append("=" * 60)
    for i, p in enumerate(posts, 1):
        lines.append("")
        lines.append(f"[{i}] {p['kind']}")
        lines.append(f'    "{p["text"]}"')
        if p.get("options"):
            lines.append("    Poll options:")
            for opt in p["options"]:
                lines.append(f"      - {opt}")
    lines.append("")
    lines.append("-" * 60)
    lines.append("Tip: polls get the most engagement. Post 1-2 a day between uploads.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6, help="roughly how many take/prediction posts")
    ap.add_argument("--polls-only", action="store_true")
    ap.add_argument("--takes-only", action="store_true")
    ap.add_argument("--save", action="store_true", help="also write a dated text file")
    args = ap.parse_args()

    cfg = _load_cfg()
    posts = generate(cfg, n=args.n, polls_only=args.polls_only, takes_only=args.takes_only)
    out = _format(posts)
    print(out)
    if args.save:
        fn = f"community_posts_{dt.date.today().isoformat()}.txt"
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(out)
            print(f"\nSaved to {fn}")
        except Exception as e:
            print(f"\n(could not save file: {e})")

