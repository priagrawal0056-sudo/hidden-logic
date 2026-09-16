# First-draft production update

Approved video title: **Why Prices Change but Barcodes Don't**.

The shared production brief now makes Gemini supply narration beats, three
role-specific footage searches, the executable mechanism, resolved visual
callback and meaningful sound cues together. Script rewrites cannot silently
leave stale timing instructions behind. The mechanism scene is derived from its
complete narration beat, and its state change follows the measured sentence
boundary. The final CTA stays separate, over the resolved animation.

The approved narration, single caption layer, navy/gold palette, continuous
smoothed music, unique footage rules and final loudness checks remain in place.
Diagram text now uses the bundled Arimo font on Windows and GitHub; asset changes
are included in cache/review fingerprints.

Validation:

- 79 tests pass, including eight first-draft contract and integration cases.
- All 79 also pass from a clean Git export containing only committed files;
  local configuration and generated outputs are absent from that export.
- 66 Python files parse; release-file scan passes and the generation CLI loads.
- Live Gemini request reached the service but ended with HTTP 429 (quota exhausted).
  No fresh Gemini-to-render result is claimed and no video was uploaded.
- A real render regression uses the approved take/assets through the brief adapter,
  with no manually supplied scene indices. Its report is saved separately from
  the approved deliverable; that video and its approval are not overwritten.
  It retains the 23.925-second runtime, passes decode/black-frame checks and
  measures -14.02 LUFS with -2.77 dBTP peak. The contact sheet was inspected.
- Latest upstream channel state through `183cb2e` was merged without conflicts.

Ready for code review and a GitHub update after the local commit. Activation still
requires service availability, the wider pilot review and current verified reserves.
This change does not enable publishing or bypass failed content/media checks.
