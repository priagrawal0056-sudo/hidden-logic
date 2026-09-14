# Hidden Logic production upgrade

The daily entry point is `autopilot.py` / `python -m credible.pipeline`.
The legacy script and stock-footage pipeline are no longer invoked by it.
Publishing remains disabled until the finished pilots have been reviewed.

## Local setup

Use an isolated environment, not the old incomplete `.runtime` directory:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-credible.txt
.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

FFmpeg uses `FFMPEG_BINARY`, then the system executable, then the complete
`imageio-ffmpeg` wheel. GitHub Actions installs system FFmpeg. Keep the free
voice and `voice_rate` stable during the experiment. No time stretching,
random pitch changes, voice cloning, fabricated human provenance or fake
recording imperfections are used.

## Build and review pilots

```powershell
.venv/Scripts/python.exe -B -m credible.pilots
```

This builds nine unpublished episodes in `outputs/pilots-v3/`, using the
previously retrieved evidence under `outputs/credible/evidence/` and the
reviewed official-page snapshots. Open `outputs/pilots-v3/review.html` and
watch at least two finished videos from each pillar with sound. A clean
checkout can first retrieve sources with `python -m credible.pipeline
--mode bootstrap`; this command builds the reserve without a Gemini key.

Check the first two seconds, usefulness of the answer, spoken delivery,
diagram accuracy, phrase captions and ending. Compare consecutive episodes
for sameness. The automated checks reject concrete problems; they cannot
prove that a video is engaging, truthful or indistinguishable from a human
production. The field `quality.passed` is **not** pilot approval.

After the owner has reviewed the actual videos, copy the generated
`pilot-review-template.json` to `state/credible/pilot_review.json`, record
the reviewer and UTC review time, and set `approved` only for accepted
videos. Six distinct accepted videos, at least two per pillar, are required.
The record contains video hashes and a production fingerprint; changing the
voice, renderer, rules or scripts invalidates the design review. Then set
`rollout_enabled` to `true`. Do not create an approval record on behalf of
an owner who has not reviewed the videos.

## What the new editorial path does

- Writes a concrete observation, an early answer, a visible explanation and
  a complete ending. The first answer must finish within six measured seconds.
- Renders the four JSON storyboard states directly. Shapes, paths, comparisons,
  labels and object movement are specific to the topic; generated scripts no
  longer fall back to the same three-box animation.
- Rejects stock phrases, leaked script directions, universal viewer claims,
  repeated sentence openings, identical drawing sequences across topics,
  label collisions and geometry outside the safe region.
- Restores script punctuation to measured speech word boundaries, including
  contractions. Captions stay in short phrases instead of straddling full stops.
- Checks the exact reviewed supporting passages for authored reserves; generated
  claims also receive a separate model review against retrieved source text.
- Stores evidence, captions, animation plans, source credits, provenance and
  checks with the episode. All original drawings are labelled as simplified
  diagrams or illustrative examples. No synthetic photorealistic footage is used.
- Revalidates cached media and invalidates it when scripts, evidence, voice,
  renderer or drawings change. Existing historical artifacts are retained.

## Connections and current deployment status

The September 14, 2026 check reached Hidden Logic and retrieved Analytics
metrics. The probed video had no retention-curve rows; absence remains unknown.
The Google Cloud browser could not be controlled during this session, and no
API setting was changed through it.

Google returned HTTP 403 for the local Gemini key and identified it as blocked
because it had been reported leaked. The generator stops further calls for
that run. Replace the key in Google AI Studio, the root `config.local.json`
(`gemini_api_key`), and the GitHub secret `HL_GEMINI_API_KEY`. Never commit or
paste credentials into review records. Do not enable billing for this workflow.

```powershell
.venv/Scripts/python.exe -B -m credible.check_generation --local-config ../config.local.json
.venv/Scripts/python.exe -B -m credible.check_analytics --token ../yt_token.pickle
```

The daily target is three Singapore slots (15:00, 19:00, 21:30), uploaded
ahead of publication. Reserves cover temporary failures, not indefinite model
outages. The nine authored topics must not be recycled. Analytics runs
separately; seven-day observations and experiment assignments remain separate
from editorial quality scores. Title revival and automatic comment replies
remain disabled.
