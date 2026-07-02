"""
idea_bank.py - a validated idea bank for Hidden Logic.

These are titles mined from high-engagement Reddit "why?" questions (AskReddit, ELI5,
NoStupidQuestions, etc.) - topics that already PROVED they get engagement, instead of the
seed pool's guesses. The daily run pulls a couple of these per day (highest viral_score first,
never repeating) and fills the remaining slots with live trends + the smart pool. When the bank
runs low it warns you so you can top it up.

Storage: idea_bank.json   (list of {title, category, viral_score, used, used_date})

CLI:
    python idea_bank.py --import bank_seed.csv   # load/merge a CSV (cols: title,category,viral_score)
    python idea_bank.py --status                 # how many ideas left, by category
    python idea_bank.py --list 20                # show next 20 unused ideas (highest score first)
    python idea_bank.py --reset-used             # mark everything unused again (re-use the bank)
"""
import csv
import datetime as dt
import json
import os
import sys

BANK_PATH = "idea_bank.json"
LOW_WATER = 15  # warn when fewer than this many unused ideas remain


def _load() -> list:
    if os.path.exists(BANK_PATH):
        try:
            with open(BANK_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def _save(bank: list):
    with open(BANK_PATH, "w", encoding="utf-8") as f:
        json.dump(bank, f, indent=2, ensure_ascii=False)


def _norm(title: str) -> str:
    return "".join(c for c in title.lower() if c.isalnum())


def import_csv(csv_path: str) -> int:
    """Merge a CSV (title,category,viral_score) into the bank. De-dupes by normalized title.
    Returns the number of NEW ideas added."""
    bank = _load()
    existing = {_norm(it["title"]) for it in bank}
    added = 0
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("title") or row.get("Title") or "").strip()
            if not title:
                continue
            key = _norm(title)
            if key in existing:
                continue
            try:
                score = float(row.get("viral_score") or row.get("Viral Score") or 0)
            except Exception:
                score = 0.0
            bank.append({
                "title": title,
                "category": (row.get("category") or row.get("Category") or "").strip(),
                "viral_score": score,
                "used": False,
                "used_date": None,
            })
            existing.add(key)
            added += 1
    # keep the bank sorted best-first so picking is just "take the top unused"
    bank.sort(key=lambda it: -it.get("viral_score", 0))
    _save(bank)
    return added


def remaining() -> int:
    return sum(1 for it in _load() if not it.get("used"))


def _published_titles() -> list:
    """Titles already on the channel (so the bank never re-serves a published topic).
    Reads channel_index.json; returns [] on any failure (non-fatal)."""
    import os, json
    out = []
    for path in ("channel_index.json", "used_topics.json"):
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for v in data:
                        t = v.get("title") if isinstance(v, dict) else (v if isinstance(v, str) else None)
                        if t:
                            out.append(t)
                elif isinstance(data, dict):
                    out.extend(str(k) for k in data.keys())
            except Exception:
                pass
    return out


def _is_dup_of_published(title: str, published: list) -> bool:
    """True if `title` is a near-duplicate of something already published, using the same
    stem-matching the generator uses elsewhere. Falls back to substring match if scriptgen
    isn't importable."""
    try:
        import scriptgen
        return any(scriptgen.seeds_match(title, p) for p in published)
    except Exception:
        tl = title.lower()
        return any(p.lower() in tl or tl in p.lower() for p in published)


def pick_unused(n: int, mark_used: bool = True, log=print) -> list:
    """Return up to n unused titles, highest viral_score first, and (by default) mark them used.
    Skips ideas that are near-duplicates of already-published videos OR of an idea already
    chosen in this same pull, so the bank stops re-serving topics the channel already covered.
    Returns a list of title strings. Non-fatal: returns [] if the bank is empty/missing."""
    bank = _load()
    if not bank:
        return []
    published = _published_titles()
    unused = [it for it in bank if not it.get("used")]

    # CHANNEL IDENTITY BOOST: the channel's own data shows a clear winner cluster - topics about
    # PHYSICAL PLACES the viewer was literally inside this week and PRODUCTS they touched
    # (grocery 1,355 / McDonald's 1,184 / airport 1,179 / cinema 1,068 / phone 1,036) - and a
    # clear loser cluster of abstract place-less brain facts (cookies 93, accents 284, waiting
    # 453). A consistent identity ("the hidden design of places you go every week") also makes
    # the channel SUBSCRIBABLE instead of a generic facts feed. So on-identity topics get a
    # score boost and are picked first; off-identity topics aren't deleted - they just sink,
    # and still surface if the identity pool runs dry.
    _IDENTITY_WORDS = (
        "store", "supermarket", "grocery", "shop", "mall", "aisle", "cart", "checkout",
        "receipt", "price", "airport", "plane", "flight", "airline", "hotel", "restaurant",
        "menu", "mcdonald", "fast food", "fries", "coffee", "cafe", "drink", "popcorn",
        "cinema", "movie theater", "theater", "stadium", "gym", "casino", "ikea", "parking",
        "traffic", "road", "highway", "drive", "car", "gas station", "elevator", "escalator",
        "bathroom", "toilet", "train", "subway", "bus", "office", "hospital", "waiting room",
        "queue", "phone", "app", "packaging", "label", "vending", "hotel room", "doctor",
    )
    def _identity_bonus(it) -> float:
        blob = (str(it.get("title", "")) + " " + str(it.get("category", ""))).lower()
        return 2.0 if any(w in blob for w in _IDENTITY_WORDS) else 0.0

    unused.sort(key=lambda it: -(it.get("viral_score", 0) + _identity_bonus(it)))

    chosen = []
    chosen_titles = []
    skipped_dupes = 0
    for it in unused:
        if len(chosen) >= max(0, n):
            break
        title = it["title"]
        # skip if it duplicates a PUBLISHED video, or one already picked in THIS pull
        if _is_dup_of_published(title, published) or _is_dup_of_published(title, chosen_titles):
            skipped_dupes += 1
            # mark these as used too, so we don't re-evaluate them every single run
            if mark_used:
                it["used"] = True
                it["used_date"] = dt.date.today().isoformat()
                it["skipped_as_dup"] = True
            continue
        chosen.append(it)
        chosen_titles.append(title)

    titles = [it["title"] for it in chosen]
    if mark_used and (chosen or skipped_dupes):
        today = dt.date.today().isoformat()
        chosen_keys = {_norm(it["title"]) for it in chosen}
        for it in bank:
            if _norm(it["title"]) in chosen_keys:
                it["used"] = True
                it["used_date"] = today
        _save(bank)
    left = sum(1 for it in bank if not it.get("used"))
    if titles:
        log(f"[idea_bank] Pulled {len(titles)} idea(s) from the bank ({left} left"
            + (f", skipped {skipped_dupes} already-covered" if skipped_dupes else "") + ").")
        if left < LOW_WATER:
            log(f"[idea_bank] *** LOW: only {left} bank ideas left. Add more with "
                f"'python idea_bank.py --import yourfile.csv' (or ask for a fresh batch). ***")
    return titles


def status():
    bank = _load()
    total = len(bank)
    left = sum(1 for it in bank if not it.get("used"))
    print(f"Idea bank: {total} total, {left} unused, {total - left} used.")
    # by category
    cats = {}
    for it in bank:
        if not it.get("used"):
            cats[it.get("category", "?")] = cats.get(it.get("category", "?"), 0) + 1
    if cats:
        print("Unused by category:")
        for c, n in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"  {c}: {n}")
    if left < LOW_WATER:
        print(f"\n*** LOW: only {left} ideas left - time to top up the bank. ***")


def main():
    args = sys.argv[1:]
    if "--import" in args:
        path = args[args.index("--import") + 1]
        added = import_csv(path)
        print(f"Imported {added} new idea(s). Bank now has {remaining()} unused.")
    elif "--status" in args:
        status()
    elif "--list" in args:
        try:
            k = int(args[args.index("--list") + 1])
        except Exception:
            k = 20
        bank = _load()
        unused = sorted([it for it in bank if not it.get("used")],
                        key=lambda it: -it.get("viral_score", 0))[:k]
        for it in unused:
            print(f"  {it.get('viral_score', 0):4.1f}  [{it.get('category','?')}]  {it['title']}")
    elif "--reset-used" in args:
        bank = _load()
        for it in bank:
            it["used"] = False
            it["used_date"] = None
        _save(bank)
        print(f"Reset. All {len(bank)} ideas marked unused again.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
