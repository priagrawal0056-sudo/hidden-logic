"""Rejected alternatives do not turn a quota deferral into an operational failure."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import service_limits
from credible import pipeline
from credible.core import read, save
from credible.evidence import EditorialRejected
from credible.rejections import DraftRejected
from footage_review import RejectedFootage
from tests import test_pipeline_recovery as fixtures
from tests.test_quota_exit import exhausted


class CandidateDeferralTests(unittest.TestCase):
    def test_real_cli_rejection_then_daily_quota_exits_zero_and_saves_work(self):
        program = '''
import contextlib, sys
from unittest.mock import patch
from credible.pipeline import main
from credible.rejections import DraftRejected
from tests import test_pipeline_recovery as fixtures
from tests.test_quota_exit import exhausted
def writer(*args, topic, **kwargs):
    if topic['topic_id'] == 'topic-0':
        raise DraftRejected('Draft has no supported mechanism')
    return fixtures.draft(topic)
with fixtures.pipeline_dependencies([fixtures.brief(0), fixtures.brief(1)],
        writer, exhausted, videos=1):
    with contextlib.redirect_stdout(sys.__stdout__), patch('sys.argv',
            ['pipeline', '--mode', 'preview', '--output', sys.argv[1]]):
        main()
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-X', 'utf8', '-B', '-c', program, directory],
                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('Gemini daily quota exhausted', result.stdout)
            self.assertNotIn('Traceback', result.stderr)
            report = read(Path(directory)/'run-report.json')
            self.assertEqual(report['status'], 'deferred_quota')
            self.assertEqual(report['completed_slots'], 0)
            self.assertEqual(report['errors'], [])
            self.assertEqual(report['pending_episodes'], 1)
            self.assertEqual(len(report['rejected_candidates']), 1)
            self.assertIn('Draft has no supported mechanism', str(report['rejected_candidates']))
            state = read(Path(directory)/'preview-state'/'production.json')
            self.assertEqual(state['topics']['topic-0']['status'], 'available')
            self.assertEqual(state['topics']['topic-1']['status'], 'reserved')
            self.assertEqual(set(state['pending_episodes']), {'topic-1'})
            self.assertEqual(state['slots'], {})

    def test_editorial_and_footage_rejections_are_separate_from_quota_errors(self):
        for rejected in (EditorialRejected('Unsupported title'),
                         RejectedFootage('Every sampled clip was unsuitable')):
            with self.subTest(rejection=type(rejected).__name__):
                def writer(*args, topic, **kwargs):
                    if topic['topic_id'] == 'topic-0' and isinstance(rejected, EditorialRejected):
                        raise rejected
                    return fixtures.draft(topic)

                def prepare(episode, *args):
                    if episode['id'] == 'topic-0':
                        raise rejected
                    exhausted()

                with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                        [fixtures.brief(0), fixtures.brief(1)], writer, prepare, videos=1), \
                        patch('sys.argv', ['pipeline', '--output', directory]):
                    pipeline.main()
                    report = read(Path(directory)/'run-report.json')
                    self.assertEqual(report['status'], 'deferred_quota')
                    self.assertEqual(report['errors'], [])
                    self.assertEqual(len(report['rejected_candidates']), 1)
                    self.assertIn(str(rejected), str(report['rejected_candidates']))

    def test_rejections_without_quota_leave_unfinished_target_failed(self):
        def writer(*args, **kwargs):
            raise DraftRejected('Draft has no supported mechanism')

        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0)], writer, lambda episode, *args: episode, videos=1), \
                patch('sys.argv', ['pipeline', '--output', directory]):
            with self.assertRaises(SystemExit) as error:
                pipeline.main()
            self.assertEqual(error.exception.code, 1)
            report = read(Path(directory)/'run-report.json')
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['completed_slots'], 0)
            self.assertIsNone(report['quota'])
            self.assertEqual(len(report['rejected_candidates']), 1)
            self.assertNotIn('Draft has no supported mechanism', str(report['errors']))

    def test_untyped_or_malformed_response_errors_are_not_hidden_by_later_quota(self):
        for failure in (ValueError('Unexpected value'), TypeError('Unexpected type'),
                        KeyError('Unexpected key'),
                        service_limits.ResponseFormatError('Malformed provider verdict')):
            with self.subTest(failure=type(failure).__name__):
                def writer(*args, topic, **kwargs):
                    if topic['topic_id'] == 'topic-0':
                        raise failure
                    return fixtures.draft(topic)

                with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                        [fixtures.brief(0), fixtures.brief(1)], writer, exhausted, videos=1), \
                        patch('sys.argv', ['pipeline', '--output', directory]):
                    with self.assertRaises(SystemExit) as error:
                        pipeline.main()
                    self.assertEqual(error.exception.code, 1)
                    report = read(Path(directory)/'run-report.json')
                    self.assertEqual(report['status'], 'incomplete')
                    self.assertEqual(report['quota']['http_status'], 429)
                    self.assertIn(str(failure), str(report['errors']))
                    self.assertEqual(report['rejected_candidates'], [])

    def test_completed_target_does_not_hide_an_unrelated_failure(self):
        def writer(*args, topic, **kwargs):
            if topic['topic_id'] == 'topic-0':
                raise TypeError('Unexpected generation bug')
            return fixtures.draft(topic)

        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0), fixtures.brief(1)], writer,
                lambda episode, *args: {**episode, 'status': 'ready'}, videos=1), \
                patch('sys.argv', ['pipeline', '--output', directory]):
            with self.assertRaises(SystemExit) as error:
                pipeline.main()
            self.assertEqual(error.exception.code, 1)
            report = read(Path(directory)/'run-report.json')
            self.assertEqual(report['completed_slots'], report['planned_slots'])
            self.assertIn(report['status'], ('incomplete', 'needs_attention'))
            self.assertIn('Unexpected generation bug', str(report['errors']))
            self.assertEqual(report['rejected_candidates'], [])

    def test_typed_exception_from_upload_remains_an_operational_failure(self):
        def writer(*args, topic, **kwargs):
            if topic['topic_id'] == 'topic-1':
                exhausted()
            return fixtures.draft(topic)

        def ready(episode, root, config):
            save(root/'episodes'/episode['id']/'episode.json', episode)
            return {**episode, 'status': 'ready'}

        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0), fixtures.brief(1)], writer, ready, videos=2) as mocks, \
                patch('credible.pilots.require_pilot_review'), \
                patch('credible.state_io.checkpoint'), patch('credible.youtube.YouTube'), \
                patch('credible.youtube.deliver', side_effect=DraftRejected('Upload failed')):
            mocks['credible.pipeline.settings'].return_value['rollout_enabled'] = True
            root = Path(directory)
            with self.assertRaises(pipeline.DailyIncompleteError) as error:
                pipeline.run('publish', root, root/'state')
            self.assertNotIsInstance(error.exception, pipeline.QuotaDeferred)
            report = read(root/'run-report.json')
            self.assertEqual(report['status'], 'incomplete')
            self.assertIn('Upload failed', str(report['errors']))
            self.assertEqual(report['rejected_candidates'], [])

    def test_bootstrap_with_only_rejections_and_no_quota_stays_incomplete(self):
        def seed(root, config, docs, catalog, state, reserve, errors, limit):
            errors.append(pipeline._issue(DraftRejected('Reserve candidate rejected'),
                                          candidate_stage=True, candidate='seed'))

        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [], lambda *args, **kwargs: None, lambda *args: None) as mocks, \
                patch('sys.argv', ['pipeline', '--mode', 'bootstrap', '--output', directory]):
            mocks['credible.pipeline.seed_reserve'].side_effect = seed
            with self.assertRaises(SystemExit) as error:
                pipeline.main()
            self.assertEqual(error.exception.code, 1)
            report = read(Path(directory)/'run-report.json')
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['reserve_ready'], 0)
            self.assertIsNone(report['quota'])
            self.assertEqual(report['errors'], [])
            self.assertEqual(len(report['rejected_candidates']), 1)


if __name__ == '__main__':
    unittest.main()
