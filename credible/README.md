# Hidden Logic evidence and delivery controller

The daily entry point remains `python -m credible.pipeline` (also `autopilot.py`).
Production version 4 connects this controller to the original approved editor:
`tts.py`, `captions.py`, `visuals.py` and `assemble.py`, through `editorial_media.py`.
The evidence, duplicate-topic, scheduling, reserve and analytics records are preserved.

Read [GITHUB_UPDATE.md](../GITHUB_UPDATE.md) for current behavior, validation and
rollout requirements. Older graphics-only versions remain readable for historical
tests but cannot be published as current reserves.

Install `requirements-credible.txt` and FFmpeg, then run:

```text
python -m unittest discover -s tests -v
python release_check.py
python -m credible.pilots
```

Pilots are saved under `outputs/pilots-v4/`. New Orus narration, stock search and
sampled-frame review require their free-service credentials. The authored reserve
scripts avoid writer calls, but a new reserve video still needs narration and assets.
A failed model or footage check must remain a visible failure.

The shared profile keeps one continuous voice take, one phrase-caption layer,
distinct footage and a longer topic-specific explanation. No voice stretching,
synthetic recording imperfections or claimed human recording history are used.
Automated quality checks are not artistic approval.

Publishing stays disabled until six finished pilots (two per pillar) have actual
owner approval with matching video hashes and the current production fingerprint.
Nine unused, verified current-style reserves are the normal operating target.
Three Singapore slots remain 15:00, 19:00 and 21:30.

Preview state is separate from production. Upload retries retain the existing
private-upload recovery ledger. Analytics runs separately and compares matched
seven-day observations; missing data remains unknown. Automatic title revival,
comment replies and community posting remain disabled in this controller.
