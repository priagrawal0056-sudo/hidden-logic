"""An unpublished category pilot can reject a draft without abandoning the category."""
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import service_limits
from credible.core import read
from credible.evidence import EditorialRejected
from credible.single import build
from footage_review import RejectedFootage


@contextlib.contextmanager
def dependencies(choices, writer, preparer):
    replacements = {
        'credible.single.settings': Mock(return_value={'production_version': 4}),
        'credible.single.load_config': Mock(return_value={'gemini_api_key': 'test', 'pexels_api_key': 'test'}),
        'credible.single.FreeModel': Mock(return_value=Mock(remaining=18)),
        'credible.pipeline.history': Mock(return_value=[]),
        'credible.single.load_bank': Mock(return_value=choices),
        'credible.topic_review.reviewed_bank': Mock(side_effect=lambda bank, _: bank),
        'credible.single.shortlist': Mock(side_effect=lambda *a, **k: list(choices)),
        'credible.single.sources_for': Mock(return_value=[]),
        'credible.single.documents': Mock(return_value=({}, [])),
        'credible.single.generate_episode': Mock(side_effect=writer),
        'credible.single.script_checks': Mock(),
        'credible.evidence.verify_support': Mock(),
        'credible.single.prepare': Mock(side_effect=preparer),
    }
    with contextlib.ExitStack() as stack:
        for name, replacement in replacements.items():
            stack.enter_context(patch(name, replacement))
        yield replacements


class SingleEditorialRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.choices = [{'topic_id': str(i), 'category': 'clothing'} for i in range(3)]
        self.episode = {'id': 'approved', 'evidence': []}

    def test_rejected_draft_uses_next_eligible_topic_without_preparing_rejected_content(self):
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices, [EditorialRejected('Rejected'), self.episode],
                lambda episode, *args: episode) as mocks:
            root = Path(temp)
            self.assertEqual(build('clothing', root), self.episode)
            attempts = read(root/'attempts.json')
            self.assertEqual([a['status'] for a in attempts], ['editorial_rejected', 'ready_for_review'])
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 2)
            mocks['credible.single.prepare'].assert_called_once_with(self.episode, root,
                {'production_version': 4, 'clip_history_path': str(root/'preview-state'/'used_clips.json')})
            self.assertFalse(read(root/'result.json')['published'])

    def test_explicit_topic_does_not_switch_subject_after_rejection(self):
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices[:1], [EditorialRejected('Rejected')], Mock()) as mocks:
            with self.assertRaises(EditorialRejected):
                build('clothing', Path(temp), topic_id='0')
            self.assertEqual(mocks['credible.single.shortlist'].call_args.kwargs['n'], 1)
            mocks['credible.single.prepare'].assert_not_called()

    def test_category_rejections_are_bounded_at_three(self):
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices, [EditorialRejected('Rejected')]*3, Mock()) as mocks:
            root = Path(temp)
            with self.assertRaises(EditorialRejected):
                build('clothing', root)
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 3)
            self.assertFalse((root/'draft.json').exists())
            self.assertFalse((root/'result.json').exists())

    def test_service_failures_never_cycle_through_other_topics(self):
        for failure in (service_limits.ServiceUnavailable(429),
                        service_limits.TransientServiceError('HTTP 503'),
                        service_limits.ResponseFormatError('Malformed verdict')):
            with self.subTest(type=type(failure).__name__), tempfile.TemporaryDirectory() as temp, dependencies(
                    self.choices, [failure], Mock()) as mocks:
                with self.assertRaises(type(failure)):
                    build('clothing', Path(temp))
                self.assertEqual(mocks['credible.single.generate_episode'].call_count, 1)
                mocks['credible.single.prepare'].assert_not_called()

    def test_second_topic_checkpoint_resumes_without_regenerating_first_rejected_topic(self):
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices, [EditorialRejected('Rejected'), self.episode],
                [service_limits.TransientServiceError('HTTP 503'), self.episode]) as mocks:
            root = Path(temp)
            with self.assertRaises(service_limits.TransientServiceError):
                build('clothing', root)
            self.assertEqual(build('clothing', root), self.episode)
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 2)
            self.assertEqual(mocks['credible.single.prepare'].call_count, 2)
            self.assertEqual(read(root/'attempts.json')[0]['topic_id'], '1')

    def test_exhausted_rejected_footage_moves_to_another_reviewed_topic(self):
        alternative = {'id': 'alternative', 'evidence': []}
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices, [self.episode, alternative],
                [RejectedFootage('All selected clips irrelevant'), alternative]) as mocks:
            root = Path(temp)
            self.assertEqual(build('clothing', root), alternative)
            attempts = read(root/'attempts.json')
            self.assertEqual([a['status'] for a in attempts], ['footage_rejected', 'ready_for_review'])
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 2)
            self.assertEqual(read(root/'draft.json')['episode'], alternative)

    def test_explicit_topic_never_switches_after_footage_rejection(self):
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices[:1], [self.episode], [RejectedFootage('All clips irrelevant')]) as mocks:
            with self.assertRaises(RejectedFootage):
                build('clothing', Path(temp), topic_id='0')
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 1)
            self.assertEqual(mocks['credible.single.prepare'].call_count, 1)

    def test_temporary_media_error_keeps_selected_draft_and_stops_other_topics(self):
        with tempfile.TemporaryDirectory() as temp, dependencies(
                self.choices, [self.episode], [service_limits.ResponseFormatError('Bad assessment')]) as mocks:
            root = Path(temp)
            with self.assertRaises(service_limits.ResponseFormatError):
                build('clothing', root)
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 1)
            self.assertEqual(read(root/'draft.json')['episode'], self.episode)


if __name__ == '__main__':
    unittest.main()
