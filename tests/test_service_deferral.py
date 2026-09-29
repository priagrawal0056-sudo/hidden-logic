"""Replay the 30-request outage cascade without consuming any real API quota."""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import service_limits
import footage_review
import tts
from credible import pipeline, single
from credible.core import read, save
from credible.evidence import FreeModel
from tests import test_pipeline_recovery as fixtures
from tests.test_service_responses import response


def outage():
    return service_limits.TransientServiceError(http_status=503, kind='server_error',
        model='gemini-3.5-flash-lite', stage='script_draft')


def writer_model():
    model = FreeModel({'model': 'gemini-3.8-flash', 'fallback_model': 'gemini-3.5-flash-lite',
                       'max_model_calls': 18})
    model.key = 'private-test-key'
    return model


class ServiceCircuitTests(unittest.TestCase):
    def test_exhausted_writer_fallback_stops_all_other_gemini_work(self):
        with service_limits.session(), patch('service_limits.time.sleep'), \
                patch('requests.post', return_value=response(status=503)) as post:
            model = writer_model()
            with self.assertRaises(service_limits.TransientServiceError):
                model.call('draft', schema={'type': 'object'})
            self.assertEqual(post.call_count, 6)
            self.assertTrue(service_limits.blocked())
            self.assertEqual(service_limits.service_deferral()['http_status'], 503)
            self.assertIsNone(service_limits.quota_deferral())
            for stage in ('script_draft', 'script_review', 'footage_review', 'narration'):
                with self.assertRaises(service_limits.TransientServiceError):
                    service_limits.before_request(model='gemini-3.5-flash-lite', stage=stage)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(service_limits.TransientServiceError):
                tts._try_gemini_tts('A complete script.', str(Path(tmp)/'voice.mp3'),
                                    str(Path(tmp)/'timings.json'), 'private-test-key')
            self.assertEqual(service_limits.report()['total_attempts'], 6)
            self.assertEqual(post.call_count, 6)
        self.assertFalse(service_limits.blocked())
        with service_limits.session(), patch('requests.post', return_value=response({'supported': True})):
            self.assertEqual(writer_model().call('review'), {'supported': True})

    def test_writer_transport_failure_can_use_one_fallback_without_leaking_details(self):
        for failure in (requests.ReadTimeout('https://private/?key=secret'),
                        requests.ConnectionError('secret')):
            with self.subTest(error=type(failure).__name__), service_limits.session(), \
                    patch('service_limits.time.sleep'), patch('requests.post', side_effect=[
                        failure, failure, failure, response({'supported': True})]) as post:
                self.assertEqual(writer_model().call('review'), {'supported': True})
                self.assertEqual(post.call_count, 4)
                self.assertFalse(service_limits.blocked())
                self.assertEqual(service_limits.report()['requests'][-1]['status'], 'no_response')
                self.assertNotIn('secret', json.dumps(service_limits.report()))

    def test_exhausted_transport_fallback_has_safe_typed_deferral(self):
        with service_limits.session(), patch('service_limits.time.sleep'), \
                patch('requests.post', side_effect=requests.Timeout('https://private/?key=secret')) as post:
            with self.assertRaises(service_limits.TransientServiceError) as caught:
                writer_model().call('draft', schema={'type': 'object'})
            details = service_limits.service_deferral(caught.exception)
            self.assertEqual(details['kind'], 'timeout')
            self.assertIsNone(details['http_status'])
            self.assertTrue(service_limits.blocked())
            self.assertEqual(post.call_count, 6)
            self.assertNotIn('secret', str(caught.exception) + json.dumps(details))

    def test_terminal_footage_failure_stops_future_narration(self):
        with service_limits.session(), patch('service_limits.time.sleep'), \
                patch('footage_review._unavailable', None), \
                patch('footage_review.subprocess.run', return_value=Mock(stdout=b'frame')), \
                patch('requests.post', return_value=response(status=503)) as post:
            with self.assertRaises(service_limits.TransientServiceError):
                footage_review.assess('clip.mp4', 4, 'Test narration.', [], 'private-test-key')
            self.assertEqual(post.call_count, len(service_limits.TEXT_MODELS) * 3)
            self.assertEqual(service_limits.service_deferral()['stage'], 'footage_review')
            with self.assertRaises(service_limits.TransientServiceError):
                service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
            self.assertEqual(service_limits.report()['total_attempts'], len(service_limits.TEXT_MODELS) * 3)

    def test_untyped_errors_cannot_open_circuit_or_claim_service_deferral(self):
        for error in (RuntimeError('HTTP 503'), requests.Timeout('Stock service timeout'),
                      service_limits.ResponseFormatError('Bad verdict'), ValueError('Bad caption')):
            with self.subTest(error=type(error).__name__), service_limits.session():
                self.assertIsNone(service_limits.service_deferral(error))
                with self.assertRaises(TypeError):
                    service_limits.stop_transient(error)
                self.assertFalse(service_limits.blocked())

    def test_existing_narration_failures_get_safe_details_when_reported(self):
        # Narration exhausts bounded same-voice model alternatives before stopping.
        with tempfile.TemporaryDirectory() as tmp, service_limits.session(), \
                patch('service_limits.time.sleep'), \
                patch('requests.post', return_value=response(status=503)) as post:
            with self.assertRaises(service_limits.TransientServiceError) as caught:
                tts._try_gemini_tts('Test.', str(Path(tmp)/'voice.mp3'),
                                    str(Path(tmp)/'timings.json'), 'private-test-key')
            issue = pipeline._issue(caught.exception, candidate_stage=True, candidate='seed')
            self.assertEqual(issue['service']['http_status'], 503)
            self.assertEqual(issue['service']['stage'], 'narration')
            self.assertTrue(service_limits.blocked())
            self.assertEqual(post.call_count, len(service_limits.TTS_MODELS) * 3)

    def test_terminal_exception_keeps_service_details_after_session_reset(self):
        with self.assertRaises(service_limits.TransientServiceError) as caught:
            with service_limits.session():
                service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
                service_limits.observe(503)
                raise service_limits.TransientServiceError('Gemini narration HTTP 503')
        self.assertFalse(service_limits.blocked())
        self.assertEqual(service_limits.service_deferral(caught.exception)['http_status'], 503)
        self.assertEqual(caught.exception.request_report['total_attempts'], 1)


class PipelineServiceDeferralTests(unittest.TestCase):
    def test_six_topic_and_three_reserve_cascade_stops_after_first_bounded_writer_failure(self):
        model = writer_model()
        with tempfile.TemporaryDirectory() as tmp, fixtures.pipeline_dependencies(
                [fixtures.brief(i) for i in range(6)], lambda *a, **k: model.call('draft', schema={'type': 'object'}),
                Mock(side_effect=AssertionError('No TTS during writer outage'))) as mocks, \
                patch('requests.post', return_value=response(status=503)) as post, \
                patch('service_limits.time.sleep'), patch('sys.argv', ['pipeline', '--output', tmp]):
            pipeline.main()
            report = read(Path(tmp)/'run-report.json')
            self.assertEqual(report['status'], 'deferred_service')
            self.assertEqual(report['completed_slots'], 0)
            self.assertEqual(len(report['deferred_slots']), 3)
            self.assertEqual(report['gemini_requests']['total_attempts'], 6)
            self.assertEqual(report['errors'], [])
            self.assertIsNone(report['quota'])
            self.assertEqual(post.call_count, 6)
            self.assertEqual(mocks['credible.pipeline.generate_episode'].call_count, 1)
            mocks['credible.pipeline.prepare'].assert_not_called()
            mocks['credible.pipeline.seed_reserve'].assert_not_called()

    def test_media_outage_preserves_pending_draft_and_next_run_resumes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with fixtures.pipeline_dependencies([fixtures.brief(i) for i in range(6)],
                    lambda *a, topic, **k: fixtures.draft(topic), Mock(side_effect=outage()), videos=1) as mocks, \
                    patch('sys.argv', ['pipeline', '--output', tmp]):
                pipeline.main()
                self.assertEqual(mocks['credible.pipeline.generate_episode'].call_count, 1)
                self.assertEqual(mocks['credible.pipeline.prepare'].call_count, 1)
                mocks['credible.pipeline.seed_reserve'].assert_not_called()
            saved = read(root/'preview-state'/'production.json')
            self.assertEqual(set(saved['pending_episodes']), {'topic-0'})
            self.assertEqual(saved['topics']['topic-0']['status'], 'reserved')
            with fixtures.pipeline_dependencies([], Mock(side_effect=AssertionError('Must resume')),
                    lambda ep, *a: {**ep, 'status': 'ready'}, videos=1) as mocks:
                pipeline.run('preview', root)
                mocks['credible.pipeline.generate_episode'].assert_not_called()
                self.assertEqual(mocks['credible.pipeline.prepare'].call_count, 1)
            self.assertEqual(read(root/'run-report.json')['status'], 'ready')

    def test_ready_reserve_can_finish_slot_during_generation_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reserve = {**fixtures.draft(fixtures.brief(9)), 'status': 'ready'}
            save(root/'reserve.json', [reserve])
            with fixtures.pipeline_dependencies([fixtures.brief(0)], Mock(side_effect=outage()),
                    lambda ep, *a: ep, videos=1):
                state = pipeline.run('preview', root)
            self.assertEqual(len(state['slots']), 1)
            report = read(root/'run-report.json')
            self.assertEqual(report['status'], 'ready')
            self.assertEqual(report['completed_slots'], 1)
            self.assertTrue(report['notices'])

    def test_prior_bug_or_malformed_response_still_causes_failed_exit(self):
        for failure in (ValueError('Broken caption'), service_limits.ResponseFormatError('Malformed verdict')):
            def writer(*args, topic, **kwargs):
                if topic['topic_id'] == 'topic-0':
                    raise failure
                raise outage()
            with self.subTest(error=type(failure).__name__), tempfile.TemporaryDirectory() as tmp, \
                    fixtures.pipeline_dependencies([fixtures.brief(0), fixtures.brief(1)], writer, Mock(), videos=1), \
                    patch('sys.argv', ['pipeline', '--output', tmp]):
                with self.assertRaises(SystemExit) as caught:
                    pipeline.main()
                self.assertEqual(caught.exception.code, 1)
                report = read(Path(tmp)/'run-report.json')
                self.assertEqual(report['status'], 'incomplete')
                self.assertIn(str(failure), str(report['errors']))

    def test_state_save_failure_still_raises(self):
        def persist(path, value):
            if Path(path).name == 'run-report.json':
                raise OSError('Disk full')
            save(path, value)
        with tempfile.TemporaryDirectory() as tmp, fixtures.pipeline_dependencies(
                [fixtures.brief(0)], Mock(side_effect=outage()), Mock()), \
                patch('credible.pipeline.save', side_effect=persist), \
                patch('sys.argv', ['pipeline', '--output', tmp]):
            with self.assertRaisesRegex(OSError, 'Disk full'):
                pipeline.main()

    def test_upload_failure_remains_error_even_during_generation_deferral(self):
        def writer(*args, topic, **kwargs):
            if topic['topic_id'] == 'topic-1':
                raise outage()
            return fixtures.draft(topic)
        def ready(episode, root, config):
            save(root/'episodes'/episode['id']/'episode.json', episode)
            return {**episode, 'status': 'ready'}
        with tempfile.TemporaryDirectory() as tmp, fixtures.pipeline_dependencies(
                [fixtures.brief(0), fixtures.brief(1)], writer, ready, videos=2) as mocks, \
                patch('credible.pilots.require_pilot_review'), patch('credible.state_io.checkpoint'), \
                patch('credible.youtube.YouTube'), patch('credible.youtube.deliver', side_effect=outage()):
            mocks['credible.pipeline.settings'].return_value['rollout_enabled'] = True
            with self.assertRaises(pipeline.DailyIncompleteError) as caught:
                pipeline.run('publish', Path(tmp), Path(tmp)/'state')
            self.assertNotIsInstance(caught.exception, pipeline.ServiceDeferred)
            report = read(Path(tmp)/'run-report.json')
            self.assertEqual(report['status'], 'incomplete')
            self.assertTrue(any('slot' in row for row in report['errors']))

    def test_bootstrap_stops_after_one_failed_reserve_and_defers(self):
        real_seed = pipeline.seed_reserve
        catalog = [{'id': k, 'url': 'https://example.org/'+k} for k in ('a', 'b', 'c')]
        docs = {s['url']: {} for s in catalog}
        with tempfile.TemporaryDirectory() as tmp, service_limits.session(), \
                patch('credible.pipeline.RECIPES', [(s['id'],) for s in catalog]), \
                patch('credible.pipeline.build_recipe', side_effect=lambda r, *a, **k: {'id': r[0], 'evidence': []}), \
                patch('credible.pipeline.duplicate', return_value=None), patch('credible.pipeline.verify_support'), \
                patch('credible.pipeline.prepare', side_effect=outage()) as prepare:
            errors = []
            real_seed(Path(tmp), {'production_version': 4}, docs, catalog, {'slots': {}}, [], errors)
            self.assertEqual(prepare.call_count, 1)
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0]['service'])
        def seed(*args):
            args[6].append(pipeline._issue(outage(), candidate_stage=True, candidate='a'))
        with tempfile.TemporaryDirectory() as tmp, fixtures.pipeline_dependencies([], Mock(), Mock()) as mocks, \
                patch('sys.argv', ['pipeline', '--mode', 'bootstrap', '--output', tmp]):
            mocks['credible.pipeline.seed_reserve'].side_effect = seed
            pipeline.main()
            self.assertEqual(read(Path(tmp)/'run-report.json')['status'], 'deferred_service')

    def test_real_cli_process_exits_zero_for_service_outage_without_claiming_completion(self):
        program = '''
import contextlib,sys
from unittest.mock import Mock,patch
from credible.pipeline import main
from tests import test_pipeline_recovery as fixtures
from tests.test_service_deferral import outage
with fixtures.pipeline_dependencies([fixtures.brief(0)],Mock(side_effect=outage()),Mock()):
    with contextlib.redirect_stdout(sys.__stdout__),patch('sys.argv',['pipeline','--output',sys.argv[1]]):
        main()
'''
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', program, tmp],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertIn('temporarily unavailable', result.stdout)
            report = read(Path(tmp)/'run-report.json')
            self.assertEqual(report['status'], 'deferred_service')
            self.assertEqual(report['completed_slots'], 0)

    def test_single_preview_defers_without_hiding_other_failures(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv', ['single', '--output', tmp]), \
                patch('credible.single.build', side_effect=outage()), contextlib.redirect_stdout(io.StringIO()):
            single.main()
            report = read(Path(tmp)/'result.json')
            self.assertEqual(report['status'], 'deferred_service')
            self.assertFalse(report['published'])
            self.assertIsNone(report['quota'])
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv', ['single', '--output', tmp]), \
                patch('credible.single.build', side_effect=ValueError('Bad render')):
            with self.assertRaises(SystemExit):
                single.main()


if __name__ == '__main__':
    unittest.main()
