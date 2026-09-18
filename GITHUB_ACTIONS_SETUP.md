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
3. Keep the Gemini project on its free allowance. This code stops failed requests;
   it cannot switch off billing in a provider account.
4. Run the Daily Autopilot manually in **preview** mode. Review its artifacts and
   error report. Preview does not upload or restore YouTube credentials.
5. Build and review six pilots across the three pillars and prepare nine unused
   current-style reserves. Follow the review-record instructions in
   [GITHUB_UPDATE.md](GITHUB_UPDATE.md).
6. Only after review, enable `rollout_enabled` in `credible/settings.json`.
   The scheduled workflow prepares videos ahead of the three Singapore slots.

The daily workflow runs at 22:17 UTC (06:17 Singapore), not at the publication
times. GitHub may delay a scheduled run; reserves and advance upload reduce that
exposure. Analytics runs independently. A state-save failure blocks further uploads.

Local checks before pushing:

```text
python -m pip install -r requirements-credible.txt
python -m unittest discover -s tests -v
python release_check.py
git diff --check
```

The bundled music is from the existing user library. Retain its original licensing
record and check any attribution requirements before enabling publication.
