"""Recovery regressions using failed provider work, not live API quota."""
import contextlib
import copy
import datetime as dt
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import service_limits
from credible.core import UTC, file_hash, read, save
from credible.pipeline import DailyIncompleteError, documents, history, prepare, run, settings


AT = dt.datetime(2026, 9, 24, 0, tzinfo=UTC)


def brief(index):
    return {'topic_id': 'topic-' + str(index), 'claim_id': 'claim-' + str(index),
            'subject': 'subject-' + str(index), 'category': ('home', 'food', 'clothing')[index % 3],
            'sources': [], 'evidence_status': 'reviewed'}


def draft(topic):
    return {**topic, 'id': topic['topic_id'], 'title': 'A distinct explanation ' + topic['topic_id'],
            'production_version': 4, 'status': 'draft'}


@contextlib.contextmanager
def pipeline_dependencies(topics, generator, preparer, videos=3):
    config = {**settings(), 'videos_per_day': videos, 'topic_reviews_per_run': 0}
    model = Mock(key='test-key', exhausted=False)
    replacements = {
        'credible.pipeline.settings': Mock(return_value=config),
        'credible.pipeline.now': Mock(return_value=AT),
        'credible.core.now': Mock(return_value=AT),
        'credible.pipeline.documents': Mock(return_value=({}, [])),
        'credible.pipeline.seed_reserve': Mock(),
        'credible.pipeline.prepare': Mock(side_effect=preparer),
        'credible.pipeline.rendered_checks': Mock(return_value={'passed': True}),
        'credible.pipeline.FreeModel': Mock(return_value=model),
        'credible.pipeline.load_bank': Mock(return_value=topics),
        'credible.pipeline.shortlist': Mock(return_value=topics),
        'credible.topic_review.reviewed_bank': Mock(side_effect=lambda bank, _: bank),
        'credible.topic_review.review_queue': Mock(return_value=[]),
        'credible.pipeline.generate_episode': Mock(side_effect=generator),
        'credible.pipeline.script_checks': Mock(),
        'credible.pipeline.editorial_checks': Mock(),
    }
    with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
        for name, replacement in replacements.items():
            stack.enter_context(patch(name, replacement))
        yield replacements


class PipelineRecoveryTests(unittest.TestCase):
    def test_source_failure_reports_when_reviewed_snapshot_recovers_it(self):
        source = {'id': 'gps', 'url': 'https://example.org/source'}
        snapshot = {**source, 'text': 'Supported mechanism.', 'retrieved_at': '2026-09-18T00:00:00Z'}
        with tempfile.TemporaryDirectory() as tmp, \
             patch('credible.pipeline.read', return_value=[snapshot]), \
             patch('credible.pipeline.retrieve', side_effect=RuntimeError('Unavailable')):
            docs, errors = documents(Path(tmp), [source])
        self.assertEqual(docs[source['url']], snapshot)
        self.assertEqual(errors[0]['fallback'], 'reviewed_snapshot')
        self.assertEqual(errors[0]['retrieved_at'], snapshot['retrieved_at'])

    def test_first_video_is_prepared_before_second_writer_can_exhaust_quota(self):
        events = []
        def generate(*args, topic, **kwargs):
            events.append(('write', topic['topic_id']))
            if topic['topic_id'] == 'topic-1':
                service_limits.observe(429)
            return draft(topic)
        def ready(episode, root, config):
            events.append(('prepare', episode['id']))
            saved = read(root/'preview-state'/'production.json')
            self.assertIn(episode['id'], saved['pending_episodes'])
            return {**episode, 'status': 'ready'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pipeline_dependencies([brief(0), brief(1)], generate, ready):
                with self.assertRaises(DailyIncompleteError):
                    run('preview', root)
            self.assertEqual(events, [('write', 'topic-0'), ('prepare', 'topic-0'), ('write', 'topic-1')])
            report = read(root/'run-report.json')
            self.assertEqual(report['completed_slots'], 1)
            state = read(root/'preview-state'/'production.json')
            self.assertEqual(state['pending_episodes'], {})
            self.assertEqual(state['topics']['topic-0']['status'], 'prepared')
            self.assertEqual(state['topics']['topic-1']['status'], 'available')

    def test_quota_during_prepare_resumes_grounded_draft_without_rewriting(self):
        def generate(*args, topic, **kwargs):
            return draft(topic)
        def blocked(*args):
            service_limits.observe(429)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pipeline_dependencies([brief(0)], generate, blocked, videos=1):
                with self.assertRaises(DailyIncompleteError):
                    run('preview', root)
            saved = read(root/'preview-state'/'production.json')
            pending = saved['pending_episodes']['topic-0']
            self.assertEqual(saved['topics']['topic-0']['status'], 'reserved')
            self.assertEqual(pending['experiment']['slot_index'], 0)
            self.assertEqual(read(root/'run-report.json')['pending_episodes'], 1)
            with pipeline_dependencies([], Mock(side_effect=AssertionError('Must not rewrite')),
                                       lambda ep, *args: {**ep, 'status': 'ready'}, videos=1) as mocks:
                result = run('preview', root)
            self.assertEqual(mocks['credible.pipeline.generate_episode'].call_count, 0)
            self.assertEqual(mocks['credible.pipeline.prepare'].call_count, 1)
            self.assertEqual(len(result['slots']), 1)
            self.assertEqual(result['pending_episodes'], {})
            self.assertEqual(result['topics']['topic-0']['status'], 'prepared')

    def test_six_alternatives_prepare_only_the_three_open_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pipeline_dependencies([brief(i) for i in range(6)],
                                       lambda *a, topic, **k: draft(topic),
                                       lambda ep, *a: {**ep, 'status': 'ready'}) as mocks:
                result = run('preview', root)
            self.assertEqual(len(result['slots']), 3)
            self.assertEqual(mocks['credible.pipeline.generate_episode'].call_count, 3)
            self.assertEqual(mocks['credible.pipeline.prepare'].call_count, 3)
            self.assertEqual(set(result['topics']), {'topic-0', 'topic-1', 'topic-2'})

    def test_completed_day_replenishes_one_reserve_then_stops_when_full(self):
        generator = lambda *a, topic, **k: draft(topic)
        preparer = lambda ep, *a: {**ep, 'status': 'ready'}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pipeline_dependencies([brief(i) for i in range(6)], generator, preparer):
                run('preview', root)
            with pipeline_dependencies([brief(i) for i in range(3, 9)], generator, preparer) as mocks:
                mocks['credible.pipeline.settings'].return_value['reserve_target'] = 1
                result = run('preview', root)
                self.assertEqual(mocks['credible.pipeline.generate_episode'].call_count, 1)
            self.assertEqual(len(result['slots']), 3)
            self.assertEqual(result['pending_episodes'], {})
            self.assertEqual(len(read(root/'reserve.json')), 1)
            with pipeline_dependencies([brief(i) for i in range(4, 10)], generator, preparer) as mocks:
                mocks['credible.pipeline.settings'].return_value['reserve_target'] = 1
                run('preview', root)
                self.assertEqual(mocks['credible.pipeline.generate_episode'].call_count, 0)
            self.assertEqual(len(read(root/'reserve.json')), 1)

    def test_invalid_render_releases_topic_without_counting_a_completed_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with pipeline_dependencies([brief(0)], lambda *a, topic, **k: draft(topic),
                                       Mock(side_effect=ValueError('Missing required footage')), videos=1):
                with self.assertRaises(DailyIncompleteError):
                    run('preview', root)
            state = read(root/'preview-state'/'production.json')
            self.assertEqual(state['pending_episodes'], {})
            self.assertEqual(state['topics']['topic-0']['status'], 'available')
            self.assertEqual(state['slots'], {})

    def test_pending_claims_are_visible_to_preview_and_duplicate_checks(self):
        pending = {**draft(brief(0)), 'status': 'reserved'}
        def read_state(path, default=None):
            if str(path) == 'state/credible/production.json':
                return {'slots': {}, 'pending_episodes': {pending['id']: pending}}
            return default
        with patch('credible.pipeline.read', side_effect=read_state):
            rows = history({'slots': {}, 'pending_episodes': {pending['id']: pending}}, [])
        self.assertEqual([row['id'] for row in rows], [pending['id']])

    def test_checked_narration_survives_render_failure_and_is_reused(self):
        episode = {**draft(brief(0)), 'beats': ['A complete thought.'],
                   'storyboard': [], 'evidence': [], 'source_label': 'Primary source'}
        def voice(ep, folder, config):
            (folder/'voice.mp3').write_bytes(b'verified narration')
            save(folder/'timings.json', {'measured': True})
            return {**ep, 'duration': 24, 'scenes': [], 'captions': [], 'beats_timing': [], 'voice': {},
                    'assets': [{'path': 'voice.mp3', 'sha256': file_hash(folder/'voice.mp3')}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch('editorial_media.fingerprint', return_value=[]), \
                 patch('config_loader.load_config', return_value={}), \
                 patch('credible.pipeline.script_checks'), patch('credible.pipeline.timeline_checks'), \
                 patch('credible.pipeline.synthesize', side_effect=voice) as synth, \
                 patch('credible.pipeline.render', side_effect=[RuntimeError('Footage service failed'), None]), \
                 patch('credible.pipeline.rendered_checks', return_value={'passed': True}), \
                 patch('captions.build_ass'), patch('editorial_media.caption_records', return_value=[]):
                with self.assertRaisesRegex(RuntimeError, 'Footage service failed'):
                    prepare(episode, root, settings())
                saved = read(root/'episodes'/episode['id']/'episode.json')
                self.assertEqual(saved['status'], 'narration_ready')
                self.assertNotIn('quality', saved)
                self.assertNotIn('render_signature', saved)
                self.assertEqual(saved['timing_sha256'], file_hash(root/'episodes'/episode['id']/'timings.json'))
                ready = prepare(episode, root, settings())
                self.assertEqual(synth.call_count, 1)
                self.assertEqual(ready['status'], 'ready')
                self.assertTrue(ready['quality']['passed'])


if __name__ == '__main__':
    unittest.main()
