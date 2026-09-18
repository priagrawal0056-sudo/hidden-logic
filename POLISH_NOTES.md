# Original pipeline: sound and finishing pass

September 16 update: the shared production editor is now connected to the daily
controller. See GITHUB_UPDATE.md for current status; the historical notes below
describe the preceding finishing pass. Follow text now appears only in captions.

The selected reference remains https://m.youtube.com/shorts/4R6mFlVVlqg.

Implemented in the existing original modules:

- Full-script Gemini request preserved, with a regression test; no per-line TTS or SSML injection.
- Only detected inter-word silence over 0.65 seconds is eligible for shortening.
  Speech has 60 ms protection on each side; the removed interval and duration are recorded.
  Word timings are remapped before captions, sound cues and sentence cuts are built.
- Two-pass -14 LUFS master, -1.5 dBTP target, LRA 7; encoded output must be within
  0.7 LU and 0.3 dB peak tolerance. Failure blocks successful completion.
- Music normalized to -24 LUFS before 0.14 gain, giving approximately -41 LUFS
  before the final mix: about 26 dB below a -15 LUFS voice. Actual relative level
  depends on the take. The original music_volume is superseded by music_bed_gain.
- Up to three short synthesized scan/chime cues, authored against unique spoken
  payoff phrases. No arbitrary whoosh on every cut. Unknown phrases block the render.
- First shot gets a 4.5% push-in. Sentence-safe cuts remain enabled.
- Captions wrap and fit using font metrics within left/right margins 110/210 px,
  start y=1240 and a maximum 350 px text block, leaving the lower/right UI clear.
- Short callback plus spoken follow invitation in generation/review instructions.
  Follow overlay starts with the measured invitation. No forced speech acceleration.
- First-frame JPG exported for review; source selection asks for a clear focal
  object. The exported cover is not automatically installed as a Shorts thumbnail.
- Specific viewer question required for the existing first-comment workflow.
  Pinning remains a YouTube Studio action; the Data API has no pin method.

Music asset: music/level-bed.mp3 is copied from the user's existing
"Level - The Grey Room _ Density & Time.mp3" library asset.
No new external media was purchased or downloaded for that bed.

These changes do not make the prior rendered video's narration change in place.
A fresh full-script Orus take and completed pilot still need listening/viewing review.
Daily publishing is disabled; the current GitHub workflow still points to the
credible pipeline, not these original modules. Do not enable it as part of this fix.
