# Approved editor rollout — September 16, 2026

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
