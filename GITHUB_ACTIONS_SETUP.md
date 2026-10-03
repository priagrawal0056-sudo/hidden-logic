# Hidden Logic → GitHub Actions: Hands-Free Cloud Setup

Goal: run safe previews and unpublished editorial pilots on GitHub's servers while preserving the existing pipeline and its state. Publication is disabled until all six pilots have passed human review and both rollout flags are explicitly enabled.

This is a one-time setup (~1-2 hours). Manual pilot generation never requires YouTube OAuth and never uploads or publishes.

────────────────────────────────────────────────────────────────────────
## What you need before starting
- A GitHub account (free, no card): https://github.com/signup
- Git installed on your laptop: https://git-scm.com/downloads
- Your working MIND GLITCH folder (the one that runs locally now)
- Your pipeline working locally at least once (so yt_token.pickle exists)

────────────────────────────────────────────────────────────────────────
## STEP 1 — Make a PRIVATE GitHub repo
1. github.com → New repository
2. Name it something like `hidden-logic` (anything)
3. **Set it to PRIVATE** ← critical. Your code + state must not be public.
4. Don't add a README/gitignore yet. Create it empty.

────────────────────────────────────────────────────────────────────────
## STEP 2 — Put your code in the repo (from your laptop)

Open a terminal IN your MIND GLITCH folder, then:

    git init
    # copy the provided .gitignore into the folder FIRST (see gitignore_for_repo.txt)
    # rename it to exactly  .gitignore
    git add .
    git commit -m "initial pipeline"
    git branch -M main
    git remote add origin https://github.com/YOUR_USERNAME/hidden-logic.git
    git push -u origin main

⚠️ Before pushing, double-check `.gitignore` is in place so config.json,
client_secret.json, and yt_token.pickle are NOT uploaded. After pushing,
look at your repo on github.com and CONFIRM those 3 files are absent.
If you see them, stop and remove them — they contain your secrets.

────────────────────────────────────────────────────────────────────────
## STEP 3 — Add the workflow file
1. In your local folder, make a folder:  .github/workflows/
2. Put the provided  daily.yml  inside it:  .github/workflows/daily.yml
3. Edit the cron time at the top (it's in UTC — see the comment in the file).
   Pick when you want it to run. Singapore is UTC+8, so 3pm SGT = 7am UTC =
   cron '0 7 * * *'.
4. Commit + push:
       git add .github/workflows/daily.yml
       git commit -m "add daily workflow"
       git push

────────────────────────────────────────────────────────────────────────
## STEP 4 — Add your secrets to GitHub
Repo → Settings → Secrets and variables → Actions → "New repository secret".
Add each of these (name on left, value = your actual key):

    HL_GEMINI_API_KEY         = your Gemini key
    HL_PEXELS_API_KEY         = your Pexels key
    HL_PIXABAY_API_KEY        = your Pixabay key
    HL_FOOTBALLDATA_API_KEY   = your football-data key (or skip if unused)
    HL_ALERT_WEBHOOK_URL      = your Discord webhook URL
    CLIENT_SECRET_JSON        = paste the ENTIRE contents of client_secret.json

The YouTube token is binary, so it needs encoding first ↓

────────────────────────────────────────────────────────────────────────
## STEP 5 — Encode + add the YouTube token  (the fiddly but essential bit)

On your laptop, in the MIND GLITCH folder, run ONE of these:

  Windows PowerShell:
    [Convert]::ToBase64String([IO.File]::ReadAllBytes("yt_token.pickle")) | Set-Clipboard
    # the base64 text is now on your clipboard

  Mac/Linux:
    base64 -i yt_token.pickle | pbcopy        # mac
    base64 yt_token.pickle                    # linux (copy the output)

Then add it as a GitHub secret:
    YT_TOKEN_B64  = (paste the base64 text)

⚠️ This token can expire (esp. if unused for ~6 months, or if you revoke
access). If uploads start failing, regenerate yt_token.pickle locally and
redo this step. The failure alert (Step 7) tells you when this happens.

────────────────────────────────────────────────────────────────────────
## STEP 6 — Validate safely and build the six pilots
1. The workflow runs `python -m unittest discover -v` before any generation path. Push and PR previews are dry-run only; they never upload.
2. For the review batch, open **Actions → Hidden Logic Daily Autopilot → Run workflow**, select **Generate six unpublished editorial pilots**, and run it on the Arena working branch. The job uses `HL_GEMINI_API_KEY` plus at least one of `HL_PEXELS_API_KEY` / `HL_PIXABAY_API_KEY`; YouTube OAuth credentials are not restored or used.
3. Download the `hidden-logic-unpublished-pilots-...` artifact. Inspect all six MP4s, captions, source/license records, reviewed crops, and sampled frames. Weak or incomplete slots are reported as skipped, not silently filled.
4. The workflow persists only clip IDs/hashes reserved by successful pilot footage so later batches do not recycle it. Pilot media remains an artifact and is not committed.
5. Do not publish or merge/enable production rollout as part of pilot generation. Human review is required; only after all six are explicitly approved should the repository variables `HL_ROLLOUT_ENABLED` and `HL_PILOT_REVIEW_COMPLETE` be set to `true` under separate approval.

A manual pilot run needs `HL_GEMINI_API_KEY` and at least one stock-footage secret. Only a separate approved production run requires `YT_TOKEN_B64` and `CLIENT_SECRET_JSON`. The workflow reports missing secret names, never their values.

────────────────────────────────────────────────────────────────────────
## STEP 7 — The safety net (so you KNOW if it dies while you're busy)
Your pipeline already sends a Discord digest on each run (success + failures).
On GitHub Actions, ALSO turn on GitHub's own failure emails:
   GitHub → your Settings → Notifications → Actions →
   ✅ "Send notifications for failed workflows only"

So: a failed RUN emails you; a failed UPLOAD pings Discord. The one gap is
if the whole scheduled job never fires — GitHub is reliable, but if you go
weeks without a Discord digest, that silence is your signal to check.

────────────────────────────────────────────────────────────────────────
## Ongoing: keep publication blocked until review.
Scheduled workflow runs must not publish while the two rollout variables are false. Review the six pilot artifacts first; do not enable rollout or merge the open PR without explicit authorization. You only need to act if:
- a preview or pilot workflow fails, or
- you are ready to review the unpublished pilot batch.

## Watch your free minutes
Settings → Billing → Plans and usage. Free = 2,000 min/month. One run is
~30-50 min, so 1/day fits easily. If you run 5 videos and it's slow on
Claude-fallback days, keep an eye that you're not approaching the cap.
If you get close, drop to fewer videos/day or every-other-day.
