# Hidden Logic — Retention Playbook (research + what I changed)

Goal: lift **stayed-to-watch from ~25% toward 60%+**. The decisive insight (yours, and the research agrees): the problem is the **first 1–2 seconds** — the swipe metric — not the middle or the ending. If too many people swipe in the first second, YouTube stops recommending the video no matter how good the rest is.

---

## The diagnosis (from your own data)

- Your **0:29** "Airport Seat" Short got **3.2× views + watched longer**; your **0:48** "Airplane Food" only got 1.24×. Shorter wins.
- Your recent drafts had silently **regressed to 100–115 words (38–43s)**; your June drafts that performed were **65–80 words (~25–30s)**. The length target existed but was never enforced.
- A 25% stayed-to-watch means ~**75% swipe in the first moment** → the opening, not the body, is the bottleneck.

---

## The science (what actually stops the swipe)

**1. Information-Gap Theory (Loewenstein, 1994).** Curiosity is the feeling of a *specific, bounded* gap between what you know and what you want to know. It **peaks when you already partly know the thing** (you live it) and are shown the exact missing piece — and dies if you know nothing or everything. This is *why* the everyday-frustration niche works: viewers already experience the thing, so a precise "here's the hidden reason" creates maximum pull. The fix is to put that specific gap in the **first ~6 words**, not after a setup.

**2. Open loops / Zeigarnik effect.** Unfinished information keeps the prefrontal cortex active until it's resolved; interrupted tasks are remembered ~2× as well. Open the loop early, pay it off **late**, never resolve it in the first 5 seconds. Open-loop hooks show ~**+32% watch time**.

**3. Negativity bias / loss aversion.** People feel losses ~2× as hard as equivalent gains, so "it's costing you / you're being steered / it's on purpose" beats a neutral fact. Negative-frame hooks consistently win A/B tests.

**4. The swipe is sub-1-second.** Good swipe-away is ≤30%; you want **80%+ retained in the first 3s**. Above ~40% swipe, the algorithm suppresses the video regardless of later AVD. The first frame + first words **are the packaging** (the Shorts equivalent of a thumbnail/title).

**5. Clarity speed.** Often the issue isn't the hook itself but **how fast the video says what it is**. If the viewer spends 2 seconds figuring out the subject, they're already gone.

**6. Pattern interrupts + captions + pace.** Refresh the frame every 2–4s; a pattern interrupt in the first 5s adds ~23% retention; ~80% watch muted so big synced captions are essential; a tight 20–30s cut beats a slow 45s.

---

## What I changed in the pipeline

**Length (the dominant lever) — now enforced, not just suggested.**
- Hard cap of **82 words (~30s)** with a gate that rejects over-length scripts and forces a "cut it down" rewrite (`scriptgen.py`). Verified: your 100–115 word drafts get rejected; 65–80 word drafts pass.
- Length targets tightened and re-weighted toward shorter; the fallback "best" script now **prefers the length-compliant one** even at a slightly lower score, so a 48s video never ships on score alone.
- Length enforced in the write, review, AND revise prompts.
- TTS pace nudged up (+8–13%) — slow talking kills retention.

**The first 1–2 seconds — rebuilt around the curiosity gap.**
- The old hook rule optimized for a "physical moment" that could be a slow setup. The **new Curiosity-Gap Hook Rule** requires the first sentence to do BOTH at once: (1) instantly name the familiar thing (zero figuring-out time) and (2) open a *specific, bounded* hidden-reason gap — framed as a loss/manipulation. Grounded in information-gap theory + open loops + negativity bias.
- New **swipe-stop score (0–10)** in the script reviewer that grades ONLY the first 1–1.5 seconds, with a hard gate (≥8) and the **top-priority rewrite** (after length). This is the metric that maps to your stayed-to-watch.
- A **repurposable hook-pattern library** (10 proven structures: "It's on purpose", "Wrong assumption", "It's costing you", "Hidden number", "Someone decided this", etc.). The writer now drafts 3 hooks each on a *different* rotating pattern and picks the strongest — your "repurpose proven hooks for unlimited ideas" idea, codified. (It also fixes the old habit of reusing the same airport example every time.)

These stack with the caption-sync, sentence-aware caption, and loudness fixes from the main audit (all of which help the first-second read).

---

## What to do on your side (high-leverage, manual)

1. **Build the competitor hook file you described.** Pick 8–10 channels in this niche, log their first-line hooks + how fast they show the subject. Drop the best *structures* into `CURIOSITY_HOOK_PATTERNS` in `scriptgen.py` — the engine will rotate and repurpose them automatically.
2. **Watch the retention graph, not just views.** The new analytics window fix means real stayed-to-watch/AVD will start populating; once you have ~12 videos with data, the now-valid A/B test and weekly calibration will tell you which hooks actually hold.
3. **Title = the feed's curiosity gap.** Keep titles plain but bounded-mysterious ("Restaurants Don't Want You Buying Medium"), pointing at the same gap the first line opens.

---

## Sources

- [Curiosity, Information Gaps, and the Utility of Knowledge (Golman & Loewenstein, CMU)](https://www.cmu.edu/dietrich/sds/docs/golman/golman_loewenstein_curiosity.pdf)
- [An Information-Gap Theory of Feelings About Uncertainty (CMU)](https://www.cmu.edu/dietrich/sds/docs/golman/Information-Gap%20Theory%202016.pdf)
- [Information Gap Theory — Ignorance Graph](https://www.ignorancegraph.com/information-gaps/information-gap-theory/)
- [The Zeigarnik Effect: Definition, Examples & Research](https://super-productivity.com/blog/zeigarnik-effect-productivity/)
- [The First 3 Seconds: Hook Structures That Stop Scroll on Shorts](https://virvid.ai/blog/first-3-seconds-hook-faceless-shorts-2026)
- [YouTube Shorts Hook Formulas That Drive 3-Second Holds — OpusClip](https://www.opus.pro/blog/youtube-shorts-hook-formulas)
- [Viewed vs. Swiped Away: The Shorts Metric That Matters — ReelRise](https://reelrise.app/guide/viewed-vs-swiped-away-the-only-youtube-shorts-metric-that-matters/)
- [The Ideal YouTube Shorts Length & Format for Retention — OpusClip](https://www.opus.pro/blog/ideal-youtube-shorts-length-format-retention)
- [How to Increase Retention & Watch-Time on Shorts (70%+) — Virvid](https://virvid.ai/blog/ai-shorts-increase-retention-watch-time)
- [The Science of Hooks: Content That Stops the Scroll](https://thebettercontentclub.com/the-science-of-hooks-creating-content-that-stops-the-scroll)
