# Hidden Logic — Automated Shorts Pipeline

**Current production update:** [Approved editor and GitHub rollout](GITHUB_UPDATE.md).
**Topic selector update:** [Research status, shared bank and verification](docs/TOPIC_SELECTOR_UPDATE.md).
The version-4 scheduler now reuses the original narration and editing modules,
with distinct footage, a longer mechanism demonstration, one caption layer and
a complete callback/CTA. Publishing remains disabled for finished-pilot review.
The older feature inventory below describes the legacy runner; use the linked
rollout document and [Actions setup](GITHUB_ACTIONS_SETUP.md) for current defaults.

Hidden Logic is a faceless YouTube Shorts channel that explains the **hidden systems behind everyday frustrations** — why milk is at the back of the store, why airport gates change last minute, why your cart keeps getting bigger. This repo is the full automation pipeline: it picks a topic, writes and fact-checks a script, voices it, captions it, fetches relevant b‑roll, renders a vertical Short, makes a thumbnail, uploads on a schedule, then learns from performance and engages with comments — hands‑off.

Everything runs on free tiers (Gemini, Edge TTS, Pexels/Pixabay, YouTube Data API). The only paid option is ElevenLabs for a premium voice, which is optional.

---

## How it works (one daily run)

1. **Topic** — picked from the idea bank, a seed×format matrix, or a live trend (`scriptgen.py`, `idea_bank.py`, `trends.py`).
2. **Script + review** — Gemini writes the script, then a second "retention analyst" pass fact‑checks it and rewrites for hook/escalation/delayed‑reveal. Multiple quality gates must pass or the slot is skipped.
3. **Voice** — ElevenLabs if keys are set, otherwise free Edge TTS (`tts.py`). Word timings come from Whisper alignment when available.
4. **Captions** — word‑synced `.ass` captions with pop‑in animation and gold emphasis (`captions.py`).
5. **B‑roll** — Pexels/Pixabay clips, ranked for relevance by Gemini (first frame = the de‑facto Shorts thumbnail) (`visuals.py`).
6. **Assemble** — ffmpeg builds a 1080×1920 / 30 fps Short with grade, music bed, SFX, and the Hidden Logic wordmark (`assemble.py`).
7. **Upload** — scheduled to your publish slots via the YouTube Data API; first comment + self‑like seeded (`upload.py`).
8. **Learn + engage** — analytics polling, winner/loser memory, A/B variants, auto‑replies, weekly insight report (`analytics_poll.py`, `winner_memory.py`, `boost.py`).

---

## One‑time setup (~45 min)

**1. Install Python 3.11+ and ffmpeg.** Tick "Add Python to PATH". Install ffmpeg with `winget install ffmpeg`, then confirm `ffmpeg -version`.

**2. Install dependencies.** In the project folder: `pip install -r requirements.txt`. If you use conda, install into the same env your scheduler will use (see Troubleshooting).

**3. Create `config.json`.** Copy `config.example.json` to `config.json` and fill it in (keys explained below).

**4. Get free API keys.**
- Gemini: https://aistudio.google.com/apikey → `gemini_api_key`
- Pexels: https://www.pexels.com/api/ → `pexels_api_key`
- Pixabay (optional, more b‑roll): https://pixabay.com/api/docs/ → `pixabay_api_key`
- Discord webhook (run alerts): a channel → Integrations → Webhooks → `alert_webhook_url`

**5. Create the YouTube channel** and confirm in Studio → Settings → Channel that it is **NOT made for kids** (otherwise comments/likes fail).

**6. Enable the upload API.** In Google Cloud Console: new project → enable **YouTube Data API v3** → OAuth consent screen (External, add your Gmail as a test user) → Create OAuth client ID (Desktop app) → download JSON → rename to `client_secret.json` in the project folder. To avoid 7‑day token expiry, click **Publish app** on the consent screen.

**7. First test run:** `python run_daily.py --dry-run --count 1` builds a video without uploading. Watch `drafts/<id>/short.mp4`. Then `python run_daily.py --count 1` does the first real upload (a browser opens once to authorize).

---

## Running it

- `python run_daily.py` — full run, uses `videos_per_day` from config.
- `python run_daily.py --dry-run` — build without uploading (still uses Gemini/Pexels quota).
- `python autopilot.py` — zero‑input full autopilot (wraps `run_daily.py --hero`: auto‑picks the day's best topic, fills the rest, uploads on schedule).
- `python run_daily.py --upload-only` — upload already‑built drafts in `drafts/` without regenerating. `--immediate` posts now; `--max-workers N` sets parallelism.

**Schedule it (Windows Task Scheduler):** point a Basic Task at **`run_autopilot.bat`** (not `python` directly — the .bat activates your conda env, logs which interpreter ran, and checks dependencies). Tick "Run task as soon as possible after a scheduled start is missed" and "Wake the computer to run this task". The bat writes a dated log to `logs/`.

---

## Config keys

**Secrets** (prefer environment variables — see Security): `gemini_api_key`, `pexels_api_key`, `pixabay_api_key`, `alert_webhook_url`, `elevenlabs_api_keys`.

**Cadence & scheduling:**
- `videos_per_day` — videos per run (the real YouTube quota ceiling is ~6 uploads/day; see Limits).
- `bank_videos_per_day` — how many come pre‑locked from the idea bank.
- `draft_buffer_multiplier` — over‑generate by this factor, publish the best N (unselected drafts are auto‑cleaned).
- `publish_slots` — local times to schedule the day's videos, e.g. `["15:00","17:00","19:00","21:00"]`. (Legacy `spread_hours` is a fallback if no slots are set.)
- `post_first_immediately` — publish video #1 now, schedule the rest.

**Quality gates** (three thresholds): `absolute_quality_floor` (hard reject below this) < `quality_floor` < `min_quality` (target). A draft that can't clear the gates after `max_attempts_per_video` tries sacrifices its slot — that's the gate working, not a crash. Lower `min_quality` if too many slots are sacrificed.

**Generation:** `llm_provider`, `script_ab` (A/B script variants), `strict_topic_lock`.

**Voice:** `tts_engine` (`auto`), `voice`, `elevenlabs_voice_id`, `elevenlabs_model_id`, `elevenlabs_api_keys` (pool; leave blank to use free Edge — you'll see a one‑time note in the log when it falls back).

**Media:** `music_file` (folder or file), `music_volume`, `score_broll` (Gemini‑ranks b‑roll for relevance; set `false` to save Gemini quota).

**Growth:** `sequel_threshold`, `revive_view_floor`.

---

## Security (do this)

`config.json`, `client_secret.json`, and `yt_token.pickle` are **secrets**. Together they allow full control of your channel and billing. They are git‑ignored by the included `.gitignore` — keep it that way.

Best practice: move secrets out of `config.json` into environment variables, which the pipeline reads automatically (`config_loader.py`):

```
HL_GEMINI_API_KEY, HL_PEXELS_API_KEY, HL_PIXABAY_API_KEY,
HL_ALERT_WEBHOOK_URL, HL_ELEVENLABS_API_KEYS (comma-separated)
```

Set them in the Task Scheduler action or your machine environment. If keys ever live in `config.json`, you'll get a one‑time security warning on each run. **If this folder was ever zipped, shared, or pushed anywhere, rotate every key.**

---

## Limits & staying clean

- The YouTube Data API free quota is ~10,000 units/day ≈ **6 uploads/day**. The pipeline now detects quota exhaustion, stops the batch, keeps the remaining drafts, and tells you in the Discord digest. Keep `videos_per_day` at or below ~5.
- B‑roll is generic Pexels/Pixabay footage only — never add copyrighted clips or real photos.
- Accuracy builds trust: if a published video's claim looks wrong, delete it.

## Operator routine (weekly, ~15 min)

Check the Discord digest after each run (it lists what shipped with links, what's growing, what needs attention). Once a week, skim `pipeline_log.txt` for ERROR lines, glance at retention in YouTube Studio, and reply to a few comments. The weekly insight report is auto‑posted to Discord.

## Troubleshooting

- **Scheduled run produced nothing / `ModuleNotFoundError: No module named 'google'`** — the scheduler ran a different Python than the one with your packages. `run_autopilot.bat` now logs `where python` and runs a dependency check; an import failure also sends a Discord alert and writes `STARTUP_FAILED.txt`. Fix: `pip install -r requirements.txt` in the exact env the bat activates.
- **Uploads fail with auth errors** — delete `yt_token.pickle` and run once manually to re‑authorize.
- **Quota exceeded** — expected past ~6 uploads/day; remaining drafts are deferred to the next run.

## Costs

$0 on free tiers (Gemini, Edge TTS, Pexels/Pixabay, ffmpeg, YouTube API). ElevenLabs (premium voice) is the only optional paid add‑on.
