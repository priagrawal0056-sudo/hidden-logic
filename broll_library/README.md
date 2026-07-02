# broll_library — your hand-picked proof clips

Drop **portrait (9:16) .mp4 clips** into a concept folder here and the pipeline will use them as a
**reliable, always-on-anchor fallback** when Pexels/Pixabay don't return a good on-topic shot.
This is how you permanently fix a weak niche (e.g. driving never had good "brake lights" stock —
add a couple of good clips once and every future driving video can use them).

## How it works
For each video, `visuals.py` detects the scene concept (driving, supermarket, airport, …). When a
clip slot can't find a strong on-anchor match online, it copies an unused clip from
`broll_library/<that concept>/` instead of duplicating a previous clip or a generic shot.

## Folder names (must match exactly)
`driving`, `supermarket`, `airport`, `hotel`, `restaurant`, `elevator`, `phone`, `money`

## What makes a good clip
- **9:16 portrait**, ~1080×1920, 3–8 seconds, no text/watermark, no logos, royalty-free.
- **Proof, not scenery** — it should SHOW the mechanism. For `driving`: brake lights close-up,
  bumper-to-bumper traffic, a car closing the gap in a mirror, a dashcam tailgating shot.
- **On-anchor** — a `driving` clip must show a **car**, never a motorcycle/scooter/bike.
- Name them anything (`brake_lights_01.mp4`, `tailgate_dashcam.mp4`); the pipeline picks unused ones.

## Where to get them (free, commercial-use)
Pexels, Pixabay, Mixkit, Coverr — search the proof phrase (e.g. "car brake lights close up"),
download the vertical version, drop it in the matching folder.

Example: `broll_library/driving/brake_lights_closeup.mp4`
