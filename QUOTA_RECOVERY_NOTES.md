# Generation recovery fixes

A Gemini HTTP 429 can stop generation before any video is ready. The previous
pipeline wrote several drafts before preparing their media, and preview retries
did not restore their output cache. That combination wasted limited requests.

Changes:
- Prepare each approved draft before writing another; keep pending drafts in the
  durable ledger and include their claims in duplicate checks.
- Checkpoint verified narration before stock/render work and reuse its measured
  timing when retrying the same episode.
- Cache preview and unpublished-pilot output separately from production. Cache
  keys include the workflow retry number; pilot and daily workflows share a lock.
- Skip description-only Gemini footage ranking on the approved editor path;
  actual sampled-frame review remains required.
- Omit ambiguous optional sound effects instead of rejecting valid narration.
- Constrain writer output to supported drawing shapes/colours and fit narrow
  labels locally. Keep factual review, safe margins and measured timing gates.
- Distinguish explicit daily and per-minute limits where Google provides quota
  identifiers. Unknown 429 responses stay unclassified. No automatic paid fallback.
- Report incomplete production with a concise nonzero exit and saved run report.
  Test output is buffered so mocked service failures do not look like live errors.

Limits:
- A successful test suite is not proof of a successful finished episode.
- External quota and suitable unique stock availability remain live dependencies.
- Three daily uploads cannot be guaranteed on an exhausted free allowance with
  an empty reserve. Publishing remains disabled pending finished pilot approval.


## Follow-up: run 35999762325

This run progressed past quota blocking but stopped on transcript, timing,
footage and temporary provider failures. The follow-up patch:

- Recognizes unambiguous spoken contraction expansions while retaining exact
  measured boundaries and rejection of missing/extra words or changed numbers.
  The actual rejected "Why's there" / "Why is there" take is a regression fixture.
- Allows one fresh continuous Orus take with measured pacing feedback when the
  20–28-second band or six-second first-answer gate fails. The original take is
  retained; no time stretching or relaxed final timing checks are used.
- Retries temporary 502/503/504 responses with bounded backoff. Authentication
  and quota failures still stop, and every writer retry consumes its call budget.
- Validates JSON envelopes and review types. Lists, truncated output and string
  booleans cannot pass as successful media assessments.
- Searches for at most two distinct replacement clips after explicit visual
  rejection. Preserves accepted shots, narration and review checkpoints. Search
  outages do not count as selected replacements.
- Preserves pending drafts on server, network and malformed-response failures.

These changes do not certify source claims or artistic quality. Unique relevant
stock and available free-tier services remain required for a successful live run.
