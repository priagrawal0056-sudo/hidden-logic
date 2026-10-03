# Hidden Logic — Python/FFmpeg Shorts Pipeline

Hidden Logic explains supported mechanisms behind small, observable everyday moments. This repository keeps the existing Python/FFmpeg renderer, script/evidence records, analytics, upload integration, and reserve system. The editorial production path uses Gemini TTS with the fixed Orus voice, five narration-aligned stock-footage beats, verified word timings, quiet phrase captions, and fail-closed quality/publication gates.

**Publication is disabled by default.** No video may be uploaded until the six unpublished pilots have passed human review and both `rollout_enabled` and `pilot_review_complete` are explicitly enabled. A weak script, voice take, crop, clip, caption, or render is skipped rather than used to fill a slot.

---

## How the editorial pipeline works

1. **Topic and script** — the existing topic selection and evidence workflow produce a five-sentence, 45–75-word observed mini-story: concrete object/place opening, useful answer early, one supported mechanism, a practical implication, and a complete ending. Forced suspense, universal claims, invented numbers, generic AI phrasing, and spoken production directions are rejected.
2. **Orus narration** — Gemini TTS keeps the narration transcript separate from structured delivery metadata. A primary take is measured for transcript accuracy, actual word timings, pauses, pitch movement, even timing, clipping, duration, and answer timing. One alternate Orus take is allowed only after a measurable quality failure. There is no alternate voice, estimated-timing fallback, or time-stretching.
3. **Captions** — restrained phrase-level `.ass` captions use actual ASR word boundaries, safe margins, readable widths, and a short final takeaway hold. Caption fade is disabled.
4. **Stock footage** — five separate scene-specific searches follow the story in order. Sampled frames are inspected; clips must show a relevant action, match the scene, and support a reviewed source start and crop. Reused IDs/hashes, weak matches, and missing actions are rejected. Source, provider, license, creator, start, crop, frame review, and hash are recorded.
5. **FFmpeg render** — the existing vertical renderer respects the reviewed starts/crops and beat timing. Color treatment is light; loop-backs, zoom punches, whooshes, and decorative overlays are off by default. Music is opt-in. The final MP4 is checked for codecs, 1080×1920 resolution, duration, and usable audio.
6. **Reserve and upload** — machine-checkable script, evidence, title, footage, voice, caption, audio, and render gates run before a draft enters the reserve or any upload path. User rejection is final for that draft. `logs/skip_reasons.jsonl` records skipped slots. Upload routes share the publication gate.
7. **Analytics and existing integrations** — the existing channel index, analytics, reserve, comments, and compilation modules remain in place; compilation is also blocked while rollout is disabled.

---

## One-time setup

1. Install Python 3.11+ and FFmpeg/FFprobe. On Windows, `winget install ffmpeg` is one option; confirm `ffmpeg -version` and `ffprobe -version`.
2. Create a project-local environment and install dependencies:

   **Windows PowerShell:**
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   **macOS/Linux:**
   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install --upgrade pip
   .venv/bin/python -m pip install -r requirements.txt
   ```

   `faster-whisper` is required for transcript verification and actual word timings; missing ASR fails closed.
3. Copy `config.example.json` to the git-ignored `config.json`. Set Gemini and at least one stock-footage key (Pexels or Pixabay). Keep `rollout_enabled` and `pilot_review_complete` false.
4. YouTube OAuth credentials are only needed for uploads, not for local pilot generation. Keep `client_secret.json` and `yt_token.pickle` out of Git.

---

## Create and review the six unpublished pilots

The batch is two technology stories, two queue/travel stories, and two shopping/pricing stories. It keeps Orus as the only voice identity and rotates only among the three controlled delivery directions. The command is inert unless `--generate` is provided.

**Windows PowerShell:**
```powershell
.\.venv\Scripts\python.exe pilot_batch.py                 # show the plan only
.\.venv\Scripts\python.exe pilot_batch.py --generate      # generate unpublished drafts
```

**macOS/Linux:**
```bash
.venv/bin/python pilot_batch.py
.venv/bin/python pilot_batch.py --generate
```

Drafts, sampled frames, metadata, skip reasons, and `pilot_batch_report.json` are written under `pilots/unpublished/YYYYMMDD/`. That directory is git-ignored. Open its generated `index.html` for a local review index with video playback, narration, voice direction, source/license, sampled frames, and the reviewed crop/action for each available pilot. Each completed draft also has its own `index.html`. These pages are static review aids only: they have no approval or upload endpoint. The batch never calls YouTube upload APIs and writes `rollout_enabled: false`. Inspect every MP4 and its source/crop records; mark each pilot's `human_review_status` as approved or rejected. Do not enable rollout unless all six pass human review. Rejected pilots remain unpublished.

The integration from [youtube-agentic-ai-studio](https://github.com/raunakpatil/youtube-agentic-ai-studio#-quick-star) is deliberately selective: this pipeline adopts the useful human-review-before-upload presentation, implemented as a static artifact for Actions and local review. Its Quick Start's alternate TTS, image-based visuals, separate renderer, retention prompts, and direct-upload path are not used; Orus, stock footage, the existing FFmpeg renderer, evidence gates, and the publication lock remain authoritative.

### GitHub Actions

Pushes to the Arena working branch and pull-request previews remain dry-run paths. To create the pilot batch on a GitHub runner, open **Actions → Hidden Logic Daily Autopilot → Run workflow**, select **Generate six unpublished editorial pilots**, and run it. The job uses the configured Gemini/Pexels/Pixabay secrets, does not require YouTube OAuth for pilots, and attaches the `pilots/unpublished/` review package as an artifact. It persists only the stock clip IDs and hashes in `used_clips.json` so later batches cannot recycle pilot footage; rendered videos stay in the artifact, not Git. The normal scheduled/main upload path remains blocked until the publication flags are explicitly approved and enabled.

Dry-run artifacts now include each successful MP4, metadata, and static review page. If no MP4 was produced, the artifact step warns instead of adding a second workflow error; a separate diagnostics artifact retains `pipeline_log.txt`, quality skip reasons, and any partial draft metadata. The pipeline step itself still fails when it cannot produce a valid video, so a missing preview is never reported as success.

---

## Running the existing pipeline

- `python run_daily.py --dry-run --count 1` — generate and render one private local test draft; no upload.
- `python run_daily.py --upload-only` — validate and upload eligible drafts only if the shared publication gate permits it.
- `python autopilot.py` — existing scheduled/autopilot entry point; it is fail-closed while rollout flags are false.

On Windows, `run_autopilot.bat --dry-run` remains available. For Task Scheduler, point the task at `run_autopilot.bat` and set the working directory to the repository. Do not schedule a publishing run before the pilots have passed human review.

---

## Configuration

**Generation secrets** (prefer environment variables):
- `HL_GEMINI_API_KEY`
- `HL_PEXELS_API_KEY`
- `HL_PIXABAY_API_KEY` (optional if Pexels is configured)
- `HL_ALERT_WEBHOOK_URL` (optional)

**Publication safety:**
- `rollout_enabled`: keep `false` until the pilot batch has passed human review.
- `pilot_review_complete`: keep `false` until all six pilots have been reviewed and approved.
- Both must be explicitly `true` before publishing routes proceed. A pilot draft also needs `human_review_status: "approved"`.
- For GitHub Actions, the equivalent non-secret repository variables are `HL_ROLLOUT_ENABLED` and `HL_PILOT_REVIEW_COMPLETE`; leave them unset/false until review.

**TTS/editorial:** `voice` is locked to `Orus`; `gemini_tts_model` selects the Gemini model; `tts_direction` chooses the baseline delivery direction. `editorial_music_enabled` defaults to `false`. No Edge, ElevenLabs, or other voice fallback is used.

The loader uses `config.example.json` in hosted CI when the ignored `config.json` is absent, then overlays configured `HL_*` environment variables. Missing publication flags default to false.

---

## Security and quality operation

`config.json`, OAuth files, generated media, and `pilots/unpublished/` are excluded from Git. Never paste or log secret values. If credentials were exposed, rotate them.

Quality takes priority over cadence. Review the skip log rather than lowering gates to fill a slot. A failed or interrupted render is not considered a draft; an interrupted upload does not become a success marker. Run the offline regression suite with:

```bash
python -m unittest discover -v
```
