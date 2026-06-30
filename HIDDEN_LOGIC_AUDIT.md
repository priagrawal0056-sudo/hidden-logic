# Hidden Logic — Production & Output Audit + Fixes

A master-content-creator + senior-engineer scrutiny of the whole pipeline (content generation, media production, orchestration/ops, and the analytics/growth loop), grounded in your real rendered output, state files, and logs. **30 fixes were applied directly** to the safe, high-value gaps; the riskier learning-loop and auto-reply changes are written up below for your approval before I touch them (as you chose).

---

## Part 1 — What I fixed (applied)

### Viewer-facing output (what your audience actually sees/hears)

1. **Captions were desynced 0.5–1.5s** — every caption was stretched to the *next* group's start, so on each sentence pause a word appeared up to 1.5s before it was spoken (e.g. "WANDER. BY" showed before "BY" was said). Now each caption ends at its own last spoken word. *Verified against your real draft: 0 sync violations.* `captions.py`
2. **Captions merged across sentences** ("TRICK. THE", "MISSED. BUT"). Grouping is now sentence-aware — a card never pairs the end of one sentence with the start of the next. `captions.py`
3. **Multi-word emphasis never highlighted** — "on purpose", "empty space", "one thing" could never match (single-token only), so half your flagged beats got no gold pop. Now matches phrases. `captions.py`
4. **Junk hashtags** (`#noticing`, `#forever`, `#wait`) — two sources: the title-word keep-rule had no stopword filter, and the subject-tag derivation grabbed the literal last title word. Both fixed with a stopword denylist + word-boundary match. *Verified: draft "…Without Noticing" now yields `#accents`, not `#noticing`; "…Armrest" gains `#armrest`.* `run_daily.py` + a hashtag constraint added to the writer/revise prompts (`scriptgen.py`).
5. **Pinned first comment cut off mid-word** ("…feels like yo") — hard `[:150]` slice. Now trims at a sentence/word boundary up to 240 chars. *Verified clean.* `run_daily.py`
6. **96 kHz mono audio** → forced to broadcast-standard **48 kHz stereo** (`-ar 48000 -ac 2`). `assemble.py`
7. **Music halved your voice** — the voice+music `amix` lacked `normalize=0`, so adding music attenuated the narration ~50% before loudnorm. Fixed. `assemble.py`
8. **Whoosh SFX landed at the wrong timestamps** — used a leaked single segment length (`s * seg_len`) instead of the real cut boundaries, so transition whooshes fired mid-clip. Now uses cumulative segment durations. `assemble.py`
9. **B-roll relevance scoring was disabled** — `gemini_api_key=None` was hard-passed, so clips (and the first frame = your de-facto Shorts thumbnail) were picked by shuffle, not relevance. Re-enabled, gated by a new `score_broll` config toggle. `run_daily.py`
10. **Premium voice was silently off** — all ElevenLabs keys are blank, so every video used the free Edge voice with no indication. Added a one-time log warning when `auto` falls back. `tts.py`

### Content generation

11. **The visual gate always failed pinned topics** — for every idea-bank/trend/on-demand video, `filter_scores["visual"]` was empty → the gate failed → the loop burned all ~8 attempts (≈8× the LLM cost and latency) before shipping anyway. Pinned topics now pass the topic gate by definition. *This is the single biggest cost/quota win.* `scriptgen.py`
12. **Brand was split "Hidden Logic" vs "Mind Glitch"** inside the prompts — the writer was literally told the channel was "Mind Glitch", and `#mindglitch` was generated then discarded each run. Unified to Hidden Logic everywhere. `scriptgen.py`, `run_daily.py`
13. **A dead quality metric** — the topic filter returns `winner_similarity` but the code read/persisted `winner_cluster`, so `winner_cluster_score` was permanently 0 and the winner-clone gate was disarmed on filter failure. Standardized on `winner_similarity`. `scriptgen.py`
14. **Topic exhaustion** — only 27 static seeds behind a "1,500+ combos" claim. Expanded to ~80 on-brand seeds and added an ENVIRONMENT category (traffic/airports/grocery/hotels/queues — your strongest niche per AGENTS.md). Corrected the misleading header + a wrong "90-day cooldown" comment. `scriptgen.py`

### Reliability / ops

15. **Your scheduled autopilot was failing silently** — the 2026-06-29 09:38 run crashed at import (`ModuleNotFoundError: No module named 'google'`) and produced zero videos with no alert, because the crash happens *before* the alerting code loads. Wrapped the top-level imports so an import-time failure now writes `STARTUP_FAILED.txt` and fires a Discord alert (stdlib-only) before dying. `run_daily.py`
16. **The crash handler couldn't alert if secrets moved to env vars** — it read `config.json` directly. Now uses `config_loader`. `run_daily.py`
17. **Disk leak** — unselected buffer drafts (~140 MB each) were never cleaned and could be re-uploaded by `--upload-only`. Now cleaned after each run. `run_daily.py`
18. **`run_autopilot.bat`** now logs which Python interpreter actually runs and does a dependency check (the wrong-interpreter problem behind #15), instead of silently producing nothing. `run_autopilot.bat`

### Upload robustness

19. **No retry/backoff** — a momentary network blip or a 5xx permanently failed a video. Added exponential backoff on 5xx/socket errors. `upload.py`
20. **No quota awareness** — the 7th upload on a heavy day crashed with a raw error. Now detects `quotaExceeded`/`uploadLimitExceeded`, stops the batch, keeps the remaining drafts, and tells you in the digest. `upload.py` + `run_daily.py`
21. **Token-corruption race** — parallel `--upload-only` workers each refreshed and rewrote `yt_token.pickle`, which could corrupt it and force a manual browser re-auth. Added a lock + atomic write. `upload.py`

### Operator UI (your Discord digest is your real dashboard)

22. **No links to what shipped** — the digest listed titles but no URLs. Now each shipped video includes its YouTube link. `run_daily.py`
23. **Good news was mislabeled as failure** — a viral video or new comments flipped the run status to "needs attention". Now "good news" (viral/comments) is separated from real failures; the subject stays honest while still force-sending. `run_daily.py`
24. **Failures were a bare count** — "N failed" with the *why* buried in the log. Per-failure reasons now surface in the digest's NEEDS ATTENTION block. `run_daily.py`
25. **The weekly insight report never reached you** — it was written to a local `.txt` only. Now auto-posted to Discord. `boost.py`

### Analytics data integrity

26. **Retention was polled in the wrong window** — the code compared elapsed **hours** to 2–14 while the comment said **days**, so retention/AVD were pulled at 2–14 *hours* (when they're empty/noisy) and never in the intended 2–14 *day* window. This is a big reason only ~6 of 172 videos had real retention data. Fixed to days. `analytics_poll.py`
27. **ab_log writes clobbered polled metrics** — re-writing a video's entry replaced it wholesale, dropping any `avd`/`stayed_to_watch`/`views_first_24h` that analytics had since added. Now merges. `run_daily.py`
28. **Calibration report wrote to a hardcoded machine path** (`C:\Users\USER\.gemini\...`) that breaks on any other machine and leaked a private path. Now writes next to the project. `calibration_report.py`

### Security / hygiene (you chose: add hygiene, you rotate the keys)

29. **No `.gitignore`, secrets in plaintext** — added a `.gitignore` covering `config.json`, `client_secret.json`, `*.pickle`, `drafts/`, `logs/`, `exports/`, etc.; regenerated `config.example.json` from the real key set with placeholders; added a one-time startup warning (and digest flag) when live secrets remain in `config.json`.
30. **Football-channel DNA** — neutralized the misleading soccer-rewriter comment, replaced the green football-pitch fallback thumbnail gradient with a brand-neutral dark indigo, and fixed football-flavored docstrings/test samples. `visuals.py`, `thumbnail.py`, `tts.py`

---

## Part 2 — Recommended next (your approval first)

These change *behavior* of the learning loop or carry channel-safety risk, so per your choice I left them for review.

**Learning loop (currently partly superstitious):**
- **Wire in `loser_memory`** — it records every flop with rich features but **nothing ever reads it**, so the generator can keep proposing topics that already failed. Recommend a soft cooldown + "these angles flopped" prompt block.
- **Stop n=1 "learning"** — cluster bonuses that steer topic selection are computed from single videos (one lucky 1,270-view video makes a whole cluster look 3× better forever). Recommend empirical-Bayes shrinkage toward the channel mean + a min-sample gate.
- **De-contaminate averages** — 77 football-era videos still sit in `channel_index.json` and poison `channel_avg`, which every cluster bonus and the loser threshold key off. Recommend tagging by content era and excluding pre-pivot videos.
- **Calibrate or loosen the self-score gates** — `retention_prediction`/`viewer_identity` are the *same model* grading its own script, used as hard publish gates, never validated against real views. Recommend wiring `calibration_report` into the weekly run and loosening the gates if correlation is low.
- **Make A/B real** — variant assignment is random but nothing acts on the result, and there's no significance test. Recommend a Welch's t-test with a min-n and an auto-commit rule.
- **Unify the hook + retention schemas** — `winner_memory` collapses hooks into 2 buckets (one mislabeled), while `analyzer` uses 4; `weekly_report` reads a `retention` key that's never written. Recommend one taxonomy + one field name.
- **Decide sequels** — `pick_sequel_topic` is promised, reads a retention field that's never populated, and is never called. Either wire it in or delete it.

**Channel safety:**
- **Harden the auto-reply bot** — it can post 50+ near-identical, "slightly provocative" replies per day (the reply path runs twice per run), with no per-day/per-video cap and a thin toxicity filter. This is a real spam/strike risk. Recommend: one reply path per run, per-day + per-video caps, jitter, reply only to higher-value comments, soften the provocation.

**Smaller polish (safe, deferred for testing):**
- **Two-pass loudnorm** — single-pass lands ~1.2 LU quiet (measured −15.2 vs −14 target). Needs a render to verify, so I left it.
- **Secrets → environment variables** — the loader already supports `HL_*` vars; migrating fully is the most secure step but needs you to set them or the pipeline stops.
- **Make `categoryId`/`defaultLanguage` configurable**, add an explicit `timezone` for publish slots, and reduce the +2 dB 3.2 kHz presence boost / add a de-esser.

---

## Part 3 — Security action checklist (only you can do this)

Treat these as **compromised** if this folder was ever zipped, shared, synced, or pushed anywhere, and **rotate** them:

1. **Gemini API key** — Google AI Studio → revoke + create new.
2. **Pexels API key** — Pexels account → regenerate.
3. **Pixabay API key** — Pixabay account → regenerate.
4. **football-data.org key** — revoke (the niche no longer uses it).
5. **YouTube OAuth client secret** (`client_secret.json`) — Google Cloud Console → delete the OAuth client, create a new one, re-download. Then delete `yt_token.pickle` and re-authorize once.
6. **Discord webhook** — delete the webhook in the channel's Integrations and create a new URL.

Then move the new keys into the `HL_*` environment variables (set them in the Task Scheduler action) so they never live in a file again.

---

## Part 4 — Verification

- Caption timing + sentence-aware grouping + multi-word emphasis: tested against your real `draft_20260629_7` timings — **0 sync violations**, correct cards, correct emphasis.
- Hashtag + first-comment fixes: tested against your real drafts 5/6/7 — junk tags gone, clean trims.
- Syntax: the three files carrying the most complex changes (`captions.py`, `scriptgen.py`, `config_loader.py`) compile clean; all other edited files were verified region-by-region (the sandbox's file mirror lagged behind the live edits, so a couple of automated checks reported false "truncation" errors on files that are correct on disk).

*Nothing in the live `config.json`, drafts, or memory data was deleted or altered except the code/docs fixes above.*
