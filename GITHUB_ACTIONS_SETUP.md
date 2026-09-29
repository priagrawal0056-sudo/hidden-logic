# GitHub Actions setup

See [GITHUB_UPDATE.md](GITHUB_UPDATE.md) for the prepared version-4 update and
the pilot review required before activation. Do not replace the repository with
a new ZIP or discard its saved channel state.

1. Review and commit the prepared branch, then push it for review. Keep local
   `config.json`, tokens, generated outputs and virtual environments excluded.
2. Add repository Actions secrets: `HL_GEMINI_API_KEY`, at least one of
   `HL_PEXELS_API_KEY` / `HL_PIXABAY_API_KEY`, and for publishing
   `YT_TOKEN_B64` / `CLIENT_SECRET_JSON`. The token secret is the base64
   encoding of the existing YouTube OAuth token file; never put it in source.
   For `HL_GEMINI_API_KEY`, paste only the raw key into the secret value—no
   assignment, quotes, JSON or `Bearer` prefix. A separate Actions variable is
   not required. The **Gemini connection check** workflow verifies authentication
   and lists configured models without generating content; it does not test the
   remaining generation quota.
3. Keep the Gemini project on its free allowance. This code stops failed requests;
   it cannot switch off billing in a provider account.
4. Start with **Unpublished topic-bank pilots**, category `home`,
   `max_candidates: 1`. This attempts one topic and records actual Gemini request
   counts by model, stage and status in `result.json`. It does not upload.
   After a pilot succeeds, use Daily Autopilot in **preview** mode to check the
   three-slot flow. Preview does not upload or restore YouTube credentials.
5. Build and review six pilots across the three pillars and prepare nine unused
   current-style reserves. Follow the review-record instructions in
   [GITHUB_UPDATE.md](GITHUB_UPDATE.md).
6. Only after review, enable `rollout_enabled` in `credible/settings.json`.
   The scheduled workflow prepares videos ahead of the three Singapore slots.

The daily workflow runs at 22:17 UTC (06:17 Singapore), not at the publication
times. GitHub may delay a scheduled run; reserves and advance upload reduce that
exposure. Analytics runs independently. A state-save failure blocks further uploads.

`deferred_quota` and `deferred_service` are normal exits with unfinished work saved.
A green workflow with either status does not mean videos were produced: check
`completed_slots` (or the single-pilot result) in the report. Temporary Gemini
failures get up to three attempts per model, with ten-second backoff (plus normal
rate pacing), then compatible backup models. Text/vision has six configured
options; speech has three, all keeping the selected voice. Explicit per-model
quota limits skip to backups; unknown/global quota and invalid credentials do
not rotate models. Every retry counts against the existing request budget.
After all options or that budget are exhausted, new Gemini work stops; later runs retry with fresh
service state and reuse verified work. Genuine validation, upload and persistence
failures still fail the workflow. Do not enable publishing to bypass a deferral.

Local checks before pushing:

```text
python -m pip install -r requirements-credible.txt
python -m unittest discover -s tests -v
python release_check.py
git diff --check
```

The bundled music is from the existing user library. Retain its original licensing
record and check any attribution requirements before enabling publication.
