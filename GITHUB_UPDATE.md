# Approved editor rollout

## September 29 retry and model-backup update

Network timeouts previously skipped the same-model retry loop. Writing, footage
review and narration now retry temporary HTTP 408/500/502/503/504 responses,
timeouts and connection failures up to three total attempts per model. Each retry
waits ten seconds after failure; existing request-rate pacing may add more time.
Logs identify the model, stage, next attempt and backup switch without credentials.

Writing and frame review can use six explicitly configured compatible models:
3.8 Flash, 3.5 Flash Lite, 3.1 Flash Lite, 3 Flash Preview, 2.5 Flash and 2.5 Flash
Lite. Narration can use 3.1 Flash TTS Preview, 3.8 Flash TTS and 2.5 Flash Preview
TTS, preserving the complete script, selected Orus voice and measured timing
checks. These are separate text/vision and speech pools, never a change to a
different narration engine. Writing retains its 18-request run budget, counting
every retry; exhausting that budget defers saved work rather than raising a bug.

After a model exhausts its retries, subsequent work skips that failed model for
the rest of the run. An explicitly model-scoped quota limit or unavailable model
also advances to a backup; unknown/global quota, authentication failures, malformed
content and negative editorial verdicts do not trigger model shopping. Model-access
checks accept an available backup when the primary is missing and also retry
temporary failures. Exhausted service/model options keep generation disabled and
exit cleanly. Reports still distinguish unfinished work from completed videos.

An exact-hash compatibility record preserves the prior narration and stock-review
cache contracts for these transport-only edits. Future source edits invalidate
those signatures normally. Saved audio, timing and footage hashes are still checked;
prompts, voice direction, alignment, captions, music and rendering stay unchanged.

Verification covers timeout recovery on the third attempt, recovery on the third
model, all-model exhaustion, ten-second backoff plus rate pacing, real request
accounting, quota scope, metadata recovery, same-voice TTS failover, negative
footage verdicts, and saved asset compatibility. These tests use mocked services;
they do not establish live Gemini availability or certify a finished pilot.
All 339 regression tests pass and the offline release scan reports no problems.
Publishing remains disabled.

## September 29 service-outage recovery

The September 28 daily log made 30 requests after writing/review services became
unavailable, including three successful narration calls for videos whose footage
could not be checked. Terminal Gemini 502/503/504 and transport failures now open
a shared stop signal after the existing bounded attempts and configured writer
fallback. No further Gemini stage or reserve narration starts in that run.

An outage-only run saves its work and reports `deferred_service` with a successful
process exit. This means deferred work, not completed videos. Counts, failed
model/stage, actual request attempts and deferred slots remain in the report.
The next run starts with a fresh service state and resumes verified pending work.
Already completed reserves remain usable. Authentication, malformed responses,
quality failures, upload failures and state-save failures keep their real errors.

The approved narration, renderer, footage checks and their asset signatures are
unchanged. This recovery fix does not require regenerating saved verified audio
or discard accepted footage. Regression coverage replays the six-topic/three-
reserve cascade: all-503 writing now stops at four requests and starts no TTS.
All 320 tests pass; the offline release scan reports no problems. Publishing
remains disabled pending finished-pilot review.

## September 28 recovery update

Authentication with the repository's Gemini secret has passed a live metadata
check. This proves key acceptance, not remaining generation quota. Generation
now records actual HTTP attempts by model and stage. One configured free writer
fallback handles temporary server outages; quota errors stop requests and defer
unfinished work without claiming that a video was completed.

The latest failed pilot exposed two local problems: entire drawings were offset
outside the screen, and a repair request only reported the first validation
error. The editor now translates a whole fitting scene while preserving its
geometry and motion. Oversized or otherwise unsafe scenes still fail. A single
bounded rewrite receives both drawing and narration errors. Version 4 permits
a simpler unused opening sketch; all rendered diagram states retain their
checks. Freezer-topic support now comes from two directly retrieved manufacturer
documents, with reviewed excerpts available if retrieval temporarily fails.

Offline validation: 304 tests pass, including both actual failed drawings;
release scan reports no problems. Use **Unpublished topic-bank pilots**, one
category and `max_candidates: 1`, for the next end-to-end check. A green metadata
check or test suite does not certify a completed video. Publishing stays disabled.

Live checks on this update:
- [Pilot 36422480881](https://github.com/priagrawal0056-sudo/hidden-logic/actions/runs/36422480881)
  generated a draft that passed local validation. Independent review received
  HTTP 503 from both configured models. Five generation attempts, no TTS calls.
- [Delayed retry 36423218974](https://github.com/priagrawal0056-sudo/hidden-logic/actions/runs/36423218974)
  received two primary-model 503 responses and one fallback read timeout.
  Three attempts, no TTS calls. Neither run hit quota or completed a video.

Authentication and local checks are verified; fresh end-to-end rendering remains
unverified while these upstream service failures persist. Do not enable publishing
or weaken the independent review to make these runs appear successful.

The September 16 notes below describe the original approved-editor rollout;
their local-only and quota observations are historical.

## September 16 implementation notes

The evidence-led scheduler now calls the original `tts.py`, `captions.py`,
`visuals.py` and `assemble.py` through a small shared editor. `run_daily.py`
uses that same editor. Evidence, duplicate prevention, upload recovery,
Singapore slots and the independent analytics collector remain in place.

## Presentation defaults

- One complete Orus take, measured word timing, restrained music and payoff cues.
- One phrase-caption layer, at most two lines, inside the Shorts safe area.
- Unique source identities and file hashes; no repeated clips or looping to fill time.
- Real footage plus one topic-specific mechanism demonstration. Gemini authors
  the hook, answer, entire mechanism beat, payoff and separate CTA together.
  The mechanism beat drives its own measured scene span, targeting 5-8 seconds;
  no manually supplied scene index is required. The hook
  stays a stock scene. A final spoken CTA uses a moving, topic-specific resolved
  diagram state rather than unrelated outro footage. Narration is not slowed.
- The barcode demonstration keeps its identifier fixed while illustrative
  stored/returned prices change. Other subjects retain their own geometry.
- Downloaded footage receives sampled-frame checks for relevance, prominent
  retailer/staff exposure and near-identical shots. Failed review blocks that
  candidate; it does not award a passing score. Samples cannot establish consent.
- Final encoded sound must be within 0.7 LU of -14 LUFS, with peak checks.
  Music-only level smoothing reduces short dips in the source track; the bed is
  continuous across picture cuts and the voice is excluded from that smoothing.
  Loudness range is measured, not used as a human-sounding voice score.
- New scripts end with a complete payoff and brief spoken follow invitation.
  Comment questions remain drafts; this change does not post or pin comments.

`editorial_profile.json` is the shared presentation source of truth. It overrides
older local presentation switches while credentials still come from environment
variables. Production version 4 invalidates older render caches and reserves.

## GitHub preparation

The branch includes upstream state through `183cb2e`. Keep the existing
`codex/credible-shorts` branch for review. `config.json` remains on the local
machine but is removed from tracking. Generated previews, tokens and local
configuration must remain excluded. This does not remove files from Git history.

The daily workflow installs the original editor dependencies, supplies Pexels
and Pixabay credentials, caches version-4 media and exports captions/edit plans
alongside the finished video. Preview runs do not restore YouTube credentials
or commit production state. Production clip history is explicitly persisted.

## One-command unpublished generation

With the same service credentials configured, run:

```text
python -m credible.single --pillar shopping
```

This retrieves source material, asks Gemini for a complete production brief,
checks claims and structure, generates one continuous Orus take, selects and
checks footage, renders the mechanism and animated callback, and measures the
final encoded output. It never authenticates to YouTube or uploads. Failure exits
nonzero and writes a failed result instead of presenting an incomplete video as ready.

The same brief rules are present in the original writer/reviewer and the daily
evidence-led generator. Automatic validation and bounded repair remain; the aim
is no routine human recutting, not a guarantee that every model response or
stock-search result will be publishable. Invalid candidates are rejected.

The live September 16 check reached Gemini but exhausted its free quota (HTTP
429). Fresh end-to-end generation is therefore not signed off yet. Offline
contract tests and a real render using the approved narration/assets are separate
checks, not substitutes for that live test.

Required GitHub secrets: `HL_GEMINI_API_KEY`, at least one of
`HL_PEXELS_API_KEY` / `HL_PIXABAY_API_KEY`, and for publishing
`YT_TOKEN_B64` / `CLIENT_SECRET_JSON`. Check the Gemini project is using its
free allowance; the code cannot enforce a provider's billing settings.
No new paid service or voice-cloning dependency is introduced.

## Validate and roll out

1. Install `requirements-credible.txt` and FFmpeg, then run
   `python -m unittest discover -s tests -v` and `python release_check.py`.
2. Run `python -m credible.pilots`. Newly rendered narration and frame review
   need working service credentials; reserve scripts alone are not ready videos.
3. Review `outputs/pilots-v4/review.html` with sound: at least two finished pilots
   in each pillar. Record actual approvals and hashes in the generated review
   template; do not carry over approvals for superseded videos.
4. Build nine unused verified version-4 reserves. Check the run report; rendering
   or quota failure must not be mistaken for a successfully replenished reserve.
5. Only after review, install the review record under `state/credible/`, enable
   `rollout_enabled` and test a production run. Publish slots remain 15:00,
   19:00 and 21:30 Singapore time, with advance scheduling.

Publishing remains disabled. This update is prepared locally, not pushed.
The existing approved barcode narration is reused for a local shared-editor
preview; it is not counted as six reviewed production pilots. Fresh generation,
stock service review and nine new finished reserves still need a connected run.

The music bed is the existing user-supplied “Level — The Grey Room / Density &
Time” asset. Its source is recorded in `POLISH_NOTES.md`; no new license grant
was obtained in this update. Confirm the original library terms before release.
