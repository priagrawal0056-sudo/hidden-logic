# Hidden Logic → GitHub Actions: Hands-Free Cloud Setup

Goal: your pipeline runs daily on GitHub's servers, uploads to YouTube, and
remembers its state — with your laptop completely out of the picture. Free, no card.

This is a one-time setup (~1-2 hours). After it, you don't touch anything.

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
## STEP 6 — Test it by hand BEFORE trusting the schedule
1. Repo → Actions tab → "Hidden Logic Daily Autopilot" → "Run workflow"
2. Watch the live log. Confirm it:
   - installs deps, restores the token
   - generates + uploads at least one video
   - the final "Commit updated state files" step pushes a commit
3. Check YouTube: did the video appear?
4. Check your repo: is there a new "autopilot state update ..." commit?

If both happened → it works. The schedule will now run it daily, hands-free.

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
## Ongoing: you do nothing.
It runs daily, uploads, commits its own state. You only act if:
- you get a failure email/Discord alert, or
- you stop seeing the daily Discord digest (check the Actions tab).

## Watch your free minutes
Settings → Billing → Plans and usage. Free = 2,000 min/month. One run is
~30-50 min, so 1/day fits easily. If you run 5 videos and it's slow on
Claude-fallback days, keep an eye that you're not approaching the cap.
If you get close, drop to fewer videos/day or every-other-day.
