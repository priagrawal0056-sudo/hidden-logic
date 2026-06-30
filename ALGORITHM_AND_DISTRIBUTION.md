# Hidden Logic — Algorithm & Distribution Playbook

Synthesized from the creator/algorithm transcripts you shared. The first playbook (RETENTION_PLAYBOOK / CREATOR_TACTICS) covered the *content* (hook, length, novelty). This one covers the *distribution* layer — **why a short freezes at 1,000 views** and how to get past it. I've split it into what the pipeline now does for you vs. what's on you.

## The one metric that decides everything: view-to-swipe (stayed-to-watch)

Every transcript converged on this: YouTube shows your short to a small test group first; if too many **swipe in the first second**, it gets pulled from the recommendation feed and dumped into search (tiny audience) — that's the "stuck at 1k" freeze. The bar:

- **≥70% stayed-to-watch = healthy** (it keeps getting pushed). **80%+ = viral nearly every time.** Below ~70% it stalls.
- A stuck short almost always means one of two things: (1) the **first 1–2 seconds were too weak** (swipe), or (2) it reached the **wrong audience** (they swipe because it's not for them).

Everything below serves those two things.

## What the pipeline now does for you (automated)

- **Stops the swipe:** the swipe-stop gate scores the first 1–1.5s (instant clarity + a specific curiosity gap) and rejects anything weak; the triple hook (visual + spoken + on-screen text) stacks in the first second; faster pace, no dead air.
- **Keeps it short:** hard ~78-word (~25–29s) cap, weighted toward ~18–22s — short videos win the swipe test (a full 20s is watched far more than a 40s).
- **Targets the right audience:** single, consistent niche; the football back-catalogue is now excluded from the learning so the algorithm reads one clear audience profile; b-roll + sounds are topic-matched, never a mismatched trending track that would cluster you with the wrong viewers.
- **Net-information-gain gate:** avoids the "conflict radius" cap (~30k) that hits copycat content.
- **Clean metadata:** 9:16 1080×1920 frame, completely filled (no black bars → always treated as a Short); clean title with no hashtag spam; 3 hashtags max in the description; a real keyword-rich description; hidden tags.
- **Revive built in:** low-view videos are revived automatically (`revive_view_floor`), which is the safe version of the "re-upload a missed short" trick.

## What's on you (manual — the pipeline can't do these)

1. **Posting cadence — strongly consider fewer per day.** You're set to `videos_per_day: 5`. Multiple creators with millions of views warn that for a channel your size, **posting many shorts/day splits the algorithm's testing** — "4×/day and only half get picked up." The consensus sweet spot is **1–2 high-quality shorts/day**, letting each one sit and collect a clean test signal. Quality over quantity: one short that breaks out lifts the whole channel more than five average ones. Try dropping to 2–3/day and watch whether your average per-video views rise.
2. **Post when YOUR audience is active.** In Studio → Analytics → **Audience → "When your viewers are on YouTube,"** find your lightest-vs-busiest hours and set `publish_slots` to your busy window (usually evening, ~6–9pm). Posting into an active window means YouTube first shows it to *your* people, who don't swipe — a clean early signal. (Your current slots 15/17/19/21 are decent; tighten toward your real peak.)
3. **Never delete a flopped video.** Deleting signals an "unstable channel" and resets trust. Leave flops up (the pipeline's revive handles second chances).
4. **Don't self-view / no VPN / no sub-for-sub.** YouTube tracks device + IP + watch behaviour; fake/irrelevant views lower your trust score and *suppress* you. Only real chosen views count.
5. **Account warmup (for any NEW channel).** Use the Google account normally for 2–3 weeks (watch, like, comment) before first upload, so YouTube reads it as human, not a bot.
6. **Feed the hook engine.** Log 8–10 same-niche channels' opening lines and drop the *structures* into `CURIOSITY_HOOK_PATTERNS` — study **small** channels (<10k subs) in your niche, not the giants; what works for a 200-sub channel ≠ what works for MrBeast.
7. **Stay consistent.** Don't post daily then vanish for a week — pick a rhythm you can keep.

## How to read your dashboard

Watch **stayed-to-watch (swipe ratio)** above everything. If it's <70%, the problem is the **first second** (the hook), not the body — make the opening clearer/curiosity-gappier and shorter. If stayed-to-watch is high but views still stall, it's an **audience/novelty** problem (wrong viewers or too-generic an idea). The weekly report and the now-fixed analytics window will populate this for you.

*All of the above is distilled from the creator transcripts you provided; nothing here requires changing how the pipeline runs except your config choices (cadence + slots), which are yours to set.*
