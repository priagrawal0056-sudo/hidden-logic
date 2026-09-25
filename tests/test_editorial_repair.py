import copy
import json
import tempfile
import unittest
from pathlib import Path

import service_limits
from credible.evidence import EditorialRejected, generate_episode
import test_topic_pipeline


class BudgetModel:
    production_version = 4
    exhausted = False

    def __init__(self, results, directory, budget=18):
        self.results = iter(results)
        self.diagnostics_dir = directory
        self.remaining = budget
        self.prompts = []

    def call(self, prompt, schema=None):
        if self.remaining <= 0:
            raise RuntimeError('budget exhausted')
        self.remaining -= 1
        self.prompts.append(prompt)
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


class EditorialRepairTests(unittest.TestCase):
    def setUp(self):
        self.draft, self.topic, self.doc, self.good = test_topic_pipeline.GroundedTopicPipelineTests().setup_case()
        self.good['reason'] = 'The source supports the scoped explanation and useful diagram.'
        self.bad = {**self.good, 'visuals_match': False,
                    'reason': 'The price update must visibly change the current price label.'}
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def generate(self, results, budget=18):
        self.model = BudgetModel(results, self.directory.name, budget)
        return generate_episode(self.model, {self.doc['url']: self.doc}, [],
                                'question_first', topic=self.topic)

    def diagnostics(self):
        return [json.loads(p.read_text(encoding='utf-8'))
                for p in Path(self.directory.name).glob('*.json')]

    def test_targeted_repair_passes_all_validation_and_fresh_source_review(self):
        fixed = copy.deepcopy(self.draft)
        fixed['title'] = 'Why a Sale Does Not Change Your Cereal Barcode'
        result = self.generate([self.draft, self.bad, fixed, self.good])
        self.assertEqual(result['title'], fixed['title'])
        self.assertEqual(self.model.remaining, 14)
        self.assertIn(self.bad['reason'], self.model.prompts[2])
        self.assertIn('failed_draft', self.model.prompts[2])
        self.assertIn(fixed['title'], self.model.prompts[3])
        self.assertNotIn(self.bad['reason'], self.model.prompts[3])
        self.assertIn('APPROVED PRODUCTION FORMAT', self.model.prompts[1])
        self.assertIn('storyboard states 2 and 3 for beat 3', self.model.prompts[1])
        self.assertIn('separate sampled-frame review', self.model.prompts[1])
        records = self.diagnostics()
        self.assertEqual(len(records), 2)
        first = next(d for d in records if d['attempt'] == 1)
        second = next(d for d in records if d['attempt'] == 2)
        self.assertEqual(first['status'], 'rejected')
        self.assertEqual(first['verdict'], self.bad)
        self.assertEqual(first['draft']['beats'], self.draft['beats'])
        self.assertEqual(second['status'], 'accepted')
        self.assertEqual(result['editorial_review'], self.good)

    def test_repeated_rejection_stops_after_exactly_one_editorial_rewrite(self):
        with self.assertRaisesRegex(EditorialRejected, 'visuals_match'):
            self.generate([self.draft, self.bad, self.draft, self.bad])
        self.assertEqual(len(self.model.prompts), 4)
        self.assertTrue(all(d['status'] == 'rejected' for d in self.diagnostics()))

    def test_duplicate_drift_unsupported_and_corroboration_are_terminal(self):
        for field, value, expected in (
                ('duplicate', True, 'duplicate'),
                ('topic_matches', False, 'topic drift'),
                ('supported', False, 'unsupported'),
                ('needs_corroboration', True, 'corroboration')):
            with self.subTest(field=field):
                verdict = {**self.bad, field: value}
                with self.assertRaisesRegex(EditorialRejected, expected):
                    self.generate([self.draft, verdict])
                self.assertEqual(len(self.model.prompts), 2)

    def test_repair_cannot_remove_source_or_drawing_checks(self):
        invalid_source = copy.deepcopy(self.draft)
        invalid_source['evidence'][0]['passage_id'] = 'INVENTED'
        invalid_drawing = copy.deepcopy(self.draft)
        invalid_drawing['storyboard'][0]['heading'] = 'x' * 40
        for draft in (invalid_source, invalid_drawing):
            with self.subTest(draft=draft['title']):
                with self.assertRaisesRegex(ValueError, 'correction failed source/drawing validation'):
                    self.generate([self.draft, self.bad, draft])
                self.assertEqual(len(self.model.prompts), 3)
        self.assertTrue(any(d['stage'] == 'editorial-repair-validation'
                            for d in self.diagnostics()))

    def test_repair_identity_drift_and_new_unsupported_claim_never_pass(self):
        changed = copy.deepcopy(self.draft)
        changed['claim_id'] = 'a-different-mechanism'
        with self.assertRaisesRegex(ValueError, 'selected topic identity'):
            self.generate([self.draft, self.bad, changed])
        self.assertEqual(len(self.model.prompts), 3)
        with self.assertRaisesRegex(EditorialRejected, 'unsupported'):
            self.generate([self.draft, self.bad, self.draft,
                           {**self.good, 'supported': False}])
        self.assertEqual(len(self.model.prompts), 4)

    def test_initial_wrong_identity_does_not_get_rewritten(self):
        changed = copy.deepcopy(self.draft)
        changed['topic_id'] = 'wrong-topic'
        with self.assertRaisesRegex(ValueError, 'selected topic identity'):
            self.generate([changed])
        self.assertEqual(len(self.model.prompts), 1)

    def test_insufficient_budget_does_not_start_unreviewable_rewrite(self):
        with self.assertRaises(EditorialRejected):
            self.generate([self.draft, self.bad], budget=3)
        self.assertEqual(self.model.remaining, 1)
        self.assertEqual(len(self.model.prompts), 2)
        self.assertFalse(self.diagnostics()[0]['repair_planned'])

    def test_exact_repair_budget_still_requires_review(self):
        result = self.generate([self.draft, self.bad, self.draft, self.good], budget=4)
        self.assertEqual(self.model.remaining, 0)
        self.assertEqual(result['evidence_status'], 'source_checked')

    def test_quota_during_rewrite_propagates_without_an_approved_result(self):
        with self.assertRaises(service_limits.ServiceUnavailable):
            self.generate([self.draft, self.bad, service_limits.ServiceUnavailable(429)])
        self.assertEqual(len(self.model.prompts), 3)
        self.assertFalse(any(d['status'] == 'accepted' for d in self.diagnostics()))

    def test_review_outage_saves_draft_without_treating_it_as_negative_or_accepted(self):
        with self.assertRaises(service_limits.TransientServiceError):
            self.generate([self.draft, service_limits.TransientServiceError('HTTP 503')])
        record = self.diagnostics()[0]
        self.assertEqual(record['status'], 'review_unavailable')
        self.assertEqual(record['draft']['beats'], self.draft['beats'])
        self.assertIsNone(record['verdict'])

    def test_malformed_verdict_is_not_an_editorial_rejection(self):
        for malformed in ([self.good], {**self.good, 'supported': 'true'},
                          {k: v for k, v in self.good.items() if k != 'duplicate'},
                          {**self.bad, 'reason': []}):
            with self.subTest(verdict=malformed):
                with self.assertRaises(service_limits.ResponseFormatError) as caught:
                    self.generate([self.draft, malformed])
                self.assertNotIsInstance(caught.exception, EditorialRejected)
                self.assertEqual(len(self.model.prompts), 2)

    def test_no_actionable_reason_means_no_speculative_rewrite(self):
        rejected = {k: v for k, v in self.bad.items() if k != 'reason'}
        with self.assertRaises(EditorialRejected):
            self.generate([self.draft, rejected])
        self.assertEqual(len(self.model.prompts), 2)


if __name__ == '__main__':
    unittest.main()
