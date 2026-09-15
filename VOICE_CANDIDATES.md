# OmniVoice evaluation — 2026-09-15

Requested candidate: https://github.com/k2-fsa/OmniVoice

The source repository is Apache-2.0, but the model card explicitly labels the
pretrained weights CC-BY-NC because of training-data constraints:
https://huggingface.co/k2-fsa/OmniVoice#license

Do not assume that the source-code licence grants commercial use of the model.
The production voice remains Orus. No model or large dependencies were installed.

The repository supports voice design without reference audio, voice cloning and
single-request generation. A separate environment is recommended by the authors.
Its advertised GPU speed does not establish performance on the normal daily runner.
This computer reports Intel integrated graphics; local generation speed and backend
compatibility have not been tested. A non-commercial comparison is still possible.

For voice reviews, do not optimize LRA as a human-speech score. EBU guidance says
LRA is not useful for short-form material:
https://tech.ebu.ch/news/2014/12/10/ebu-helps-measure-the-loudness-o

The completed barcode revision preserves the accepted mixed Orus take, including
its measured pauses and natural emphasis. No fabricated breathing or per-sentence
TTS concatenation was introduced. The final export is near -14 LUFS and remains unpublished.
