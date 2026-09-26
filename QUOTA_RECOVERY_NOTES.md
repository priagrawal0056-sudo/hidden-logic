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

## Follow-up: run 36089523477

The unpublished clothing pilot passed all 201 regressions, then its independent
editorial review rejected the draft before narration. No verdict explanation was
saved, leaving only a generic error. The follow-up keeps the review gate and:

- Saves the draft and individual review verdicts for diagnosis.
- Gives the reviewer the same production format used by the writer and editor.
- Allows one targeted rewrite for correctable presentation failures, followed by
  fresh local checks and independent review. Unsupported claims, topic drift,
  duplicate mechanisms and missing corroboration remain hard rejections.
- Lets a category pilot try up to three eligible briefs after editorial rejection.
  Explicit topic requests never switch topics, and service failures stop the run.
- Resumes an approved alternative draft after media failure, and includes draft,
  attempted topics, timing and footage-review checkpoints in pilot artifacts.

A finished live pilot is still required; unit tests alone do not establish that
available stock, narration, and rendering all succeed together.

## Follow-up: runs 36115075962 and 36117318790

The clothing pilot passed writing and measured narration, then correctly rejected
three unrelated clips. The subsequent daily preview also rejected irrelevant
scale footage, successfully corrected a honey draft, and ultimately exhausted
the explicitly reported daily Gemini quota. It finished with one pending episode
and no completed slots.

- Preserve provider relevance order, interleave both providers, and prioritize
  literal subject matches before the twelve-candidate limit. Description matching
  only orders candidates; every clip still requires actual sampled-frame review.
- Exclude rejected/current sources before that limit so they cannot hide later
  alternatives. Changed selection code invalidates stale footage checkpoints;
  stock-only changes leave the narration contract unchanged.
- Category pilots can move to another reviewed topic after exhausting genuinely
  rejected footage. Service errors stop instead; explicit topic requests stay fixed.
- Preserve specific temporary narration service errors and malformed-audio
  failures after the existing two attempts. Record safe request outcomes, never
  keys or raw provider messages. These failures now retain the approved draft.
  This TTS implementation update changes the existing narration cache signature
  once; later retries reuse verified takes under the new signature.

Daily quota exhaustion is an external blocker, not a successful video. No further
live generation was requested after that explicit daily-limit response. Publishing
remains disabled; the updated footage selection still needs a finished live pilot.

## Expected quota deferral exits successfully

At the owner's request, a run blocked only by Gemini HTTP 429 now exits with code
0 after saving its report and recovery state. It prints the quota/rate-limit
message and records `status: deferred_quota`, with truthful completed and pending
counts. This is successful handling of a deferral, not a completed video.

Daily, per-minute and unspecified 429 responses keep distinct messages. Quota
notices and recovered source warnings are separate from errors. Authentication,
other unresolved failures, missed publication recovery and failed persistence
still fail the run. Bootstrap retains its bounded partial-progress behavior;
single previews also save an unpublished deferred result on quota exhaustion.

The workflow does not use `continue-on-error`. Its artifact and cache steps still
run, and a later invocation resumes preserved work. No extra live Gemini calls
are needed to test this exit policy.

## September 26 preview and scheduled-run recovery

The saved preview from run 36227372000 reached live narration after quota reset,
then rejected three footage selections and a late first answer before exhausting
Gemini again. This was not a quota-only failure. Its failed footage reviews include
coffee scales for a shop-scale detail, folded jeans for a zipper, and repeated
honey-stirring compositions. The pavement opening measured 6.66 seconds initially
and 6.80 seconds after its retake.

- Stock search now includes high-resolution landscape footage. The frame reviewer
  sees the same center portrait crop as the editor, and every clip still needs a
  passing review. Full-episode and shot-role context distinguishes contextual footage
  from the separate mechanism animation; pointed-out hook details must remain visible.
- Repeated-action rejections try other authored shot queries instead of requesting
  the same action again. Exhausted footage alternatives give that topic a seven-day
  cooldown while leaving it unused. Other failures retain their existing retry policy.
- The first draft now limits the hook and first answer to ten plain spoken words;
  local validation triggers correction before narration. Measured six-second checks
  and the single continuous retake remain mandatory.
- A disabled scheduled rollout exits normally with `skipped_rollout` and no API,
  credential, cache-save or production-state work. Explicit publishing remains blocked,
  and manual Preview and Bootstrap remain available. No publishing setting was enabled.

These changes have offline regression coverage. They still require a successful
finished live pilot; no tests can guarantee free-service availability or that stock
libraries contain a suitable distinct shot for every topic.
