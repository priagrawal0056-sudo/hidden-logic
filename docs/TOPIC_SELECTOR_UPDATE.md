# Everyday topic selector: implementation and release status

The production writer now starts from an explicit everyday observation and its
reviewed evidence. Daily runs, single previews and the legacy script interface
share `credible/topics.json`. The original narration, footage editor, captions,
music, callback and CTA format remain the production baseline.

## Research status — not a completed 500-verified-topic delivery

The bank contains exactly 500 authored briefs in the agreed category split.
All have received an initial source search. The research run retrieved 1,081
accessible documents from 1,394 candidate URLs. A reachable page is not proof
that it supports a claim.

Currently 200 briefs have explicit source-support reviews. Five of those have
an editorial hold because their present angle mainly explains obvious utility.
The other 300 briefs remain `pending_review`; they are not eligible to generate
or publish. Counts and current cooldown exclusions are recorded in
`topic-bank-validation.json`. The grouped review index is `TOPICS_500.md`; the
flat export is `TOPICS_500.csv`.

The remaining work is substantive: finish checking the explanations, replace
weak or unsupported premises, improve individual footage briefs, and complete
the semantic distinctness review against the bank and channel history. Unique
IDs and a clean schema do not prove that 500 mechanisms are genuinely distinct.

## Selection and unattended recovery

- Five equally weighted editorial dimensions: recognition, overlooked detail,
  payoff, evidence and visual feasibility. Each must score at least 2/4. These
  are editorial judgments, never predicted views or measured audience results.
- Six briefs across subjects and categories are shortlisted. Preparation favors
  three distinct categories and underrepresented recent categories.
- Canonical claim IDs enforce 90-day exclusions; narrow subjects have 14-day
  spacing. Title-only history receives a separate comparison. The independent
  script reviewer also checks semantic duplication and topic drift.
- Reviewed replacements regenerate their mechanism identity and narrow subject.
  Identical normalized claims cannot evade validation through different row IDs.
  Shared materials such as glass no longer group unrelated objects together.
- Selection does not consume a topic. Reservations expire only before rendering;
  prepared or uncertain uploads retain their identity until recovered. Failed
  generation or rendering releases a pre-render reservation with a retry delay.
- Pending leads receive a bounded automatic source/editorial review before
  writing when free Gemini capacity is available. Untouched leads precede older
  failures, preventing a few broken sources from starving the queue. Saved
  reviews are invalidated when their underlying brief changes. A second review
  checks the finished script against source text.
- Live reservations and reserves remain visible to previews, while preview
  writes stay isolated. Source outages do not mark topics permanently used.
- Missing daily slots now produce a failed run with a saved report and preserved
  recovery state. A report with zero completed slots cannot silently be green.

Source checks and model reviews reduce mistakes; they do not establish factual
truth merely by returning a positive score. Primary passages must be present in
retrieved documents, and surprising numerical or disputed causal claims need
independent corroboration.

Subdomains, redirects to the same publisher and known shared owners in the
source catalog cannot count as independent corroboration. Different domains
alone still do not prove editorial independence. Retrieval rejects missing-page
shells and PDF links that serve replacement HTML instead of the document.

## Compatibility and experiments

The exhausted 446-row `idea_bank.json` remains unchanged. No used flags were reset.
The new `category` field accompanies the legacy three-value `pillar` field.
The new experiment is `everyday-topics-v2`; old `early-answer-v1` observations
are reported separately. Automatic format promotion remains disabled.

The Singapore slots remain 15:00, 19:00 and 21:30. Rollout is still disabled.
Existing finite authored reserve recipes remain available, with history and
source gates. Reserve use never masquerades as a randomized opening experiment.

## Verification and GitHub handoff

Run offline checks with:

```text
python -m unittest discover -s tests -q
python release_check.py
python idea_bank.py --status
```

The tests cover missing/delayed analytics, incorrect support, paraphrased
duplicates, shared words, cooldown boundaries, reservations, failed media
assessment, caption bounds, narration mismatch, exhausted quota, reserve
consumption, timezone conversion, interrupted uploads and same-day retries.
Additional tests cover source-review fairness, saved-review invalidation, long
manual passages, preview history, topic drift, category metadata, publisher
grouping, missing-page responses and revised mechanism identity. The current
offline suite passes 133 tests.

The new **Unpublished topic-bank pilots** workflow renders one home, food and
clothing episode sequentially using existing `HL_GEMINI_API_KEY`,
`HL_PEXELS_API_KEY` and optional `HL_PIXABAY_API_KEY` secrets. It only has read
access to repository contents and receives no YouTube upload credentials. Its
artifacts include each completed video and its source/quality record, or a
failure result. No secret value is included in reports.

Live source-to-render verification has not run in this checkout because the
credentials are held in GitHub Secrets. The workflow must be run after the
reviewed changes reach GitHub. Local mock-service tests are not a substitute for
those three finished videos. Existing pilot approval and rollout gates remain.

Nothing has been pushed or published as part of this change. Do not describe
this as a completed 500-supported-topic bank or a proven intervention-free live
deployment yet. External quota, service outages and genuinely uncertain uploads
can still require attention; duplicate prevention takes priority over blindly
retrying an upload.

Latest review corrections: missed old slots cannot block current slots or trigger an expired upload; current editorial holds override cached reviews. Object-specific spacing now groups related kettle topics together and separates refrigerators from the incidental milk in their titles. The two remaining editorial holds stay ineligible.

18 September update: category-to-slot assignment uses actual publication history and covers available slots before allocating backups. A 21-day simulation checks rotation and separately balanced opening formats; this is not a guarantee of audience outcomes.
