# Creator Tactics → What I Applied to Hidden Logic

Distilled from the creator transcripts you shared (MrBeast; the 3-billion-views marketer; Halls the faceless-Shorts editor; the "Shorts jail" creator; John Scott on the 2026 algorithm; and the growth channels). I kept only what applies to a faceless explainer-Shorts channel and built it into the pipeline.

## The big ideas (and where they're now enforced)

**1. The triple hook — visual + spoken + on-screen TEXT.** The "Shorts jail" creator: subtitles are NOT a hook; you need a separate text line that *adds* to the story. You already had the spoken hook and (now) a scored visual first frame. **Added:** the writer produces a distinct `text_hook` (e.g. "ON PURPOSE", "YOU'VE BEEN TRICKED") and assembly renders it big at the top for the first ~2.3s, separate from the captions. *(scriptgen.py + assemble.py + run_daily.py)*

**2. The first ~1 second is the packaging.** MrBeast (autoplay → you must make them click AND watch at once, first 5s drives CTR) + the marketer (brain decides in <1s) + the swipe data (>40% swipe → algorithm drops you). **Enforced:** the new swipe-stop score grades ONLY the first 1–1.5s (instant clarity + a specific curiosity gap) with a hard gate and the top-priority rewrite. *(from the retention work)*

**3. Net information gain / the swap test (the 2026 conflict-radius).** John Scott: YouTube caps videos that just repeat an idea many channels made (stalls ~30k); rewording someone's script with ChatGPT lands everyone in the same "conflict radius." **Added:** a `novelty_score` gate — the script must add a specific new number, a non-obvious second mechanism, a fresh analogy, or a counterintuitive twist, and pass the swap test ("could this sit on any other channel?"). Generic scripts get rejected and pushed to add a unique angle. *(scriptgen.py)*

**4. Match, then exceed.** MrBeast: the opening must immediately confirm the title's promise, then over-deliver — no tangents. **Added** as an explicit writer rule, reinforcing that the first line and title point at the same gap.

**5. People share reactions, not facts.** The marketer + the Shorts-jail creator (start with the emotion: LOL/WTF/OMG/no way). **Added** a target-reaction rule: write toward one specific, easily-retold payoff a viewer would send to a friend.

**6. Shorter always wins; cut all dead space.** Everyone said it; Halls cuts every 2–5s with no silence; the Shorts-jail creator's golden rule ("never make it longer for retention"). **Enforced:** the hard 82-word/~30s length gate + faster TTS + leading-silence trim + fixed transition SFX/cuts. (Your own data already proved it: 29s beat 48s 3×.)

**7. Repurpose proven formats, don't invent.** MrBeast ("do it 100× better and make it mine") + the marketer (familiarity/mere-exposure beats originality). **Added:** the rotating `CURIOSITY_HOOK_PATTERNS` library — drop competitor hook *structures* in and the writer repurposes them automatically.

## What's still on you (the transcripts are right that some of this is manual)

- **Build the competitor file.** 8–10 channels, log their first-line hooks + how fast they reveal the subject, and add the best *structures* to `CURIOSITY_HOOK_PATTERNS`. This is the single highest-leverage manual input.
- **Ride trends.** The pipeline has trend seeds, but a human spotting "everyone's talking about X right now" still beats automation. Feed timely angles in via the idea bank.
- **Volume + iteration (MrBeast's core point).** "Make 100 videos, improve one thing each time." The pipeline now improves automatically (length, hook, novelty gates; the now-running calibration + valid A/B test), but judgment on what to make is yours.
- **Net information gain is ultimately about ideas.** The gate forces a new angle, but the *best* new angles (a surprising stat, a fresh mechanism) come from you or better source material.

## Net effect on the funnel

- **Swipe (stayed-to-watch):** triple hook + swipe-stop gate + instant-clarity rule + length cap → fewer first-second swipes.
- **Distribution (getting past ~30k):** novelty/swap-test gate → less likely to be capped in the conflict radius.
- **Watch-through / loops:** shorter scripts, faster pace, fixed caption sync, abrupt-end + return-hook → higher % viewed.
- **Repeat viewing:** stronger payoffs + binge series → the "watch 10 videos" effect MrBeast described.
