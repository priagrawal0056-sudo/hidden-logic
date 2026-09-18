# GitHub release review — 17 September 2026

Decision updated 18 September: **owner approved GitHub publication with the current 200 source-reviewed briefs (198 eligible; two editorial holds)**. Remaining research is deferred; live rollout acceptance remains incomplete. GitHub-only publication is authorized after review; YouTube rollout remains disabled. Do not describe the bank as 500 researched, publishable briefs yet.

## Corrected defects

- **Overdue slots blocking current delivery:** publication time is checked before any upload lookup or insert. The pipeline records expired slots for recovery, preserves their upload state and reservations, and continues with future slots. Tests cover prepared, uncertain and already-uploaded expired slots plus a same-day retry. An overdue slot remains a visible needs-attention result even when current slots succeed.
- **Cached reviews overriding editorial holds:** the review fingerprint includes every authored brief field. Current holds and authored completed reviews take precedence over saved automated reviews. Tests cover changed scores, notes, visual plans and scope, plus holds that must never reach the model.
- **Incorrect subject spacing:** compilation identifies the main object before incidental words. Fridges no longer become milk topics; kettle mechanisms share a spacing group while retaining separate claim IDs. Tests distinguish water fixtures and dairy products. This corrects object grouping; it does not prove semantic distinctness across the entire bank.

## Research progress and remaining acceptance

- Exactly 500 rows retain the agreed category totals. **200 have source reviews; 300 remain pending.** Two reviewed briefs still have editorial holds and cannot be selected.
- All 200 supporting passages were matched against the dated local retrieved documents. Context was reviewed before approval. Literal matching is not independent proof of causal support and is not a fresh online re-fetch.
- Three previously held utility angles were replaced with mechanisms involving kettle steam controls, intumescent fire-door seals and T-shirt spirality. Original drafts remain in research inputs for audit; the final bank uses the reviewed replacements.
- JSON, CSV and grouped index rebuild identically without local raw-search files or the downloaded source cache. JSON and CSV contain the same 500 IDs in the same order.
- The history scan covers 560 records. Full semantic distinctness review across all 500 briefs and history remains unfinished; unique IDs do not establish it.
- Three finished new-category pilots have not yet been generated and reviewed. The unpublished pilot workflow is prepared, but is not on GitHub. Mock tests cannot establish narration, footage or finished visual quality.

## Validation

- 133 regression tests pass, including the corrected failure paths.
- The prior release scan and Python parse check passed; rerun them on the final copied file set before committing.
- Approved narration, editor, caption, music/profile settings and the exhausted historical idea bank have not been intentionally changed. Verify their diff before release.
- `rollout_enabled` remains false. No live generation or publishing result is implied by passing mock-backend tests.

## GitHub access and action scope

The existing GitHub Desktop credential has owner push permission. A branch push dry-run succeeded; required secret names are present. The separate CLI login is invalid but does not prevent use of the working Git credential helper. No secret values were printed or saved.

No commit, push, merge, workflow dispatch or YouTube upload has been performed. The owner has deferred the remaining 300 source reviews. Complete unpublished live pilots and the remaining distinctness checks before claiming live rollout acceptance. External quota outages and genuinely uncertain uploads can still require recovery; the system must not hide them or retry blindly.

18 September update: category-to-slot assignment uses actual publication history and covers available slots before allocating backups. A 21-day simulation checks rotation and separately balanced opening formats; this is not a guarantee of audience outcomes.

## Approved reduced launch scope

The 500-row file retains 300 pending research leads for later work; it is not advertised as 500 supported topics. Automatic review of pending leads is disabled with `topic_reviews_per_run: 0`, so daily selection uses the authored reviewed pool. Two editorial holds remain excluded. Publishing remains disabled. GitHub publication is approved for the upgrade branch; this does not constitute a merge into main or a completed live render test.
