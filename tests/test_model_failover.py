"""Retry/failover scenarios use fake time and HTTP; no real quota is consumed."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import service_limits as limits
import footage_review
import tts
from credible.core import read
from credible.evidence import FreeModel
from credible.service_check import check
from tests.test_service_responses import response
from tests.test_tts_service_recovery import response as audio_response


def quota(model_scoped=True):
    result = response(status=429)
    result.json.return_value = {'error': {'details': [{'violations': [{
        'quotaId': 'GenerateRequestsPerDayPerProject' + ('PerModel' if model_scoped else ''),
        'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
        'quotaValue': '20'}]}]}}
    return result


class ModelFailoverTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.waits = []
        self.enterContext(patch('service_limits.time.monotonic', side_effect=lambda: self.clock))
        self.enterContext(patch('service_limits.time.sleep', side_effect=self.advance))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def advance(self, delay):
        self.waits.append(delay)
        self.clock += delay

    def test_two_real_duration_timeouts_retry_same_request_after_ten_seconds(self):
        starts = []
        payload = object()
        def send():
            starts.append(self.clock)
            if len(starts) < 3:
                self.clock += 75
                raise requests.ReadTimeout('private-key')
            return payload
        payload = response({'ok': True})
        with limits.session():
            self.assertIs(limits.request_with_retry(send, model='gemini-2.5-flash', stage='writing'), payload)
            self.assertFalse(limits.blocked())
            self.assertEqual(limits.report()['total_attempts'], 3)
        self.assertEqual(starts, [0, 85, 170])
        self.assertEqual(self.waits, [10, 10])

    def test_fast_failures_keep_minimum_rate_pacing_and_no_sleep_after_success(self):
        starts = []
        def send():
            starts.append(self.clock)
            return response(status=503) if len(starts) < 3 else response({})
        with limits.session():
            limits.request_with_retry(send, model='gemini-2.5-flash', stage='writing')
        self.assertEqual(starts, [0, 15, 30])
        self.assertEqual(self.waits, [10, 5, 10, 5])

    def test_every_temporary_http_status_retries_and_can_recover(self):
        for status in (408, 500, 502, 503, 504):
            with self.subTest(status=status), limits.session():
                send = Mock(side_effect=[response(status=status), response({})])
                limits.request_with_retry(send)
                self.assertEqual(send.call_count, 2)
                self.assertFalse(limits.blocked())

    def test_mixed_transport_failures_reach_third_model_and_keep_payload(self):
        model = FreeModel({'model': limits.TEXT_MODELS[0],
                          'fallback_models': list(limits.TEXT_MODELS[1:3]), 'max_model_calls': 10})
        model.key = 'private-key'
        with limits.session(), patch('requests.post', side_effect=
                [requests.Timeout('private-key')] * 3 + [response(status=503)] * 3 +
                [response({'supported': True}), response({'supported': True})]) as post:
            self.assertEqual(model.call('exact prompt'), {'supported': True})
            self.assertEqual(model.call('next review'), {'supported': True})
            self.assertFalse(limits.blocked())
            self.assertEqual(limits.report()['total_attempts'], 8)
        self.assertEqual(model.remaining, 2)
        self.assertIn(limits.TEXT_MODELS[2] + ':', post.call_args_list[6].args[0])
        bodies = [call.kwargs['json'] for call in post.call_args_list[:7]]
        self.assertTrue(all(body == bodies[0] for body in bodies))

    def test_all_configured_writer_models_are_tried_then_circuit_stops(self):
        settings = read(Path(__file__).resolve().parents[1] / 'credible/settings.json')
        model = FreeModel(settings)
        model.key = 'private-key'
        with limits.session(), patch('requests.post', side_effect=requests.Timeout('private-key')) as post:
            with self.assertRaises(limits.TransientServiceError):
                model.call('draft')
            self.assertTrue(limits.blocked())
            count = len(model.chain.models) * 3
            self.assertEqual(post.call_count, count)
            self.assertEqual(limits.report()['total_attempts'], count)
            with self.assertRaises(limits.TransientServiceError):
                limits.before_request(stage='narration')
            self.assertEqual(post.call_count, count)

    def test_remaining_budget_cannot_be_reset_by_switching_model(self):
        model = FreeModel({'model': limits.TEXT_MODELS[0],
                          'fallback_models': list(limits.TEXT_MODELS[1:]), 'max_model_calls': 4})
        model.key = 'private-key'
        with limits.session(), patch('requests.post', return_value=response(status=503)) as post:
            with self.assertRaises(limits.TransientServiceError) as error:
                model.call('draft')
            self.assertEqual(post.call_count, 4)
            self.assertEqual(model.remaining, 0)
            self.assertEqual(limits.service_deferral(error.exception)['kind'], 'request_budget')

    def test_missing_and_model_exhausted_allowances_skip_to_working_backup(self):
        for first in (response(status=404), quota()):
            with self.subTest(status=first.status_code), limits.session():
                chain = limits.ModelChain(limits.TEXT_MODELS[:2])
                send = Mock(side_effect=[first, response({'ok': True})])
                chain.request(send, stage='writing')
                self.assertEqual(send.call_count, 2)
                self.assertEqual(chain.model, limits.TEXT_MODELS[1])
                self.assertFalse(limits.blocked())
                # Another consumer in this run skips the known failed model.
                next_chain = limits.ModelChain(limits.TEXT_MODELS[:2])
                next_send = Mock(return_value=response({}))
                next_chain.request(next_send, stage='footage_review')
                next_send.assert_called_once_with(limits.TEXT_MODELS[1])

    def test_all_model_quotas_exhausted_preserve_quota_exit_and_actual_counts(self):
        with limits.session():
            chain = limits.ModelChain(limits.TEXT_MODELS)
            send = Mock(side_effect=lambda model: quota())
            with self.assertRaises(limits.ServiceUnavailable) as error:
                chain.request(send, stage='writing')
            self.assertEqual(send.call_count, len(limits.TEXT_MODELS))
            self.assertEqual(limits.quota_deferral()['limit_kind'], 'daily')
            self.assertEqual(error.exception.request_report['total_attempts'], len(limits.TEXT_MODELS))
            self.assertTrue(limits.blocked())

    def test_global_or_unknown_quota_and_auth_never_rotate_even_without_session(self):
        for result in (quota(False), response(status=429), response(status=401), response(status=403)):
            for in_session in (False, True):
                with self.subTest(status=result.status_code, session=in_session), \
                        (limits.session() if in_session else contextlib.nullcontext()):
                    send = Mock(return_value=result)
                    with self.assertRaises(limits.ServiceUnavailable):
                        limits.ModelChain(limits.TEXT_MODELS).request(send, stage='writing')
                    self.assertEqual(send.call_count, 1)

    def test_failed_model_memory_resets_next_run_and_deduplicates_config(self):
        for _ in range(2):
            with limits.session():
                chain = limits.ModelChain([limits.TEXT_MODELS[0]] * 2)
                send = Mock(return_value=response(status=503))
                with self.assertRaises(limits.TransientServiceError):
                    chain.request(send, stage='writing')
                self.assertEqual(send.call_count, 3)

    def test_bad_request_and_invalid_content_do_not_shop_for_passing_verdict(self):
        for result in (response(status=400), response({'supported': False})):
            with limits.session():
                send = Mock(return_value=result)
                self.assertIs(limits.ModelChain(limits.TEXT_MODELS).request(send, stage='writing'), result)
                self.assertEqual(send.call_count, 1)

    def test_footage_timeout_recovers_on_backup_but_negative_verdict_still_rejects(self):
        valid = {'relevant': False, 'exposure_ok': True, 'distinct': True, 'description': 'Unrelated road.'}
        with tempfile.TemporaryDirectory() as tmp, limits.session(), \
                patch('footage_review._unavailable', None), \
                patch('footage_review.subprocess.run', return_value=Mock(stdout=b'frame')), \
                patch('requests.post', side_effect=[requests.Timeout()] * 3 + [response(valid)]) as post:
            with self.assertRaises(footage_review.RejectedFootage):
                footage_review.assess(Path(tmp)/'clip.mp4', 4, 'Product barcode.', [], 'private-key')
            self.assertEqual(post.call_count, 4)
            self.assertFalse(limits.blocked())

    def test_narration_uses_multiple_tts_models_but_exact_same_voice_and_script(self):
        with tempfile.TemporaryDirectory() as tmp, limits.session(), \
                patch.object(tts, '_TTS_CFG', {'gemini_voice': 'Orus'}), \
                patch('requests.post', side_effect=[requests.Timeout()] * 3 +
                    [audio_response(503)] * 3 + [audio_response()]) as post, \
                patch.object(tts, '_ffmpeg', return_value='ffmpeg'), patch.object(tts.subprocess, 'run'), \
                patch.object(tts, '_apply_speed'), patch.object(tts, '_align_with_whisper', return_value=[
                    {'word': 'Complete.', 'start': 0, 'end': 1}]):
            voice = str(Path(tmp)/'voice.mp3')
            tts._try_gemini_tts('Complete.', voice, voice+'.timings.json', 'private-key')
            self.assertEqual(post.call_count, 7)
            bodies = [call.kwargs['json'] for call in post.call_args_list]
            self.assertTrue(all(body == bodies[0] for body in bodies))
            self.assertEqual(bodies[0]['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'], 'Orus')
            self.assertEqual(read(voice+'.service.json')['attempts'][-1]['model'], limits.TTS_MODELS[-1])
            self.assertFalse(limits.blocked())

    def test_connection_check_accepts_available_backup_when_primary_is_missing(self):
        get = Mock(return_value=Mock(status_code=200, json=Mock(return_value={'models': [
            {'name': 'models/gemini-2.5-flash', 'supportedGenerationMethods': ['generateContent']}]})))
        result = check('private-key', {'writing': 'gemini-3.8-flash'}, get,
                       model_pools={'writing': ['gemini-3.8-flash', 'gemini-2.5-flash']})
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(result['available_by_role'], {'writing': ['gemini-2.5-flash']})
        self.assertNotIn('private-key', json.dumps(result))

    def test_connection_check_retries_timeout_then_server_error_before_success(self):
        ok = Mock(status_code=200, json=Mock(return_value={'models': [
            {'name': 'models/gemini-2.5-flash', 'supportedGenerationMethods': ['generateContent']}]}))
        get = Mock(side_effect=[requests.Timeout('private-key'), Mock(status_code=503), ok])
        result = check('private-key', {'writing': 'gemini-2.5-flash'}, get)
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(get.call_count, 3)
        self.assertEqual(self.waits, [10, 10])

    def test_metadata_outage_exhaustion_exits_cleanly_and_does_not_enable_generation(self):
        from credible.service_check import main
        for status in ('service_unavailable', 'model_unavailable', 'rate_limited'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)/'result.json'
                github_output = Path(tmp)/'github-output'
                with patch('sys.argv', ['service_check', '--output', str(out)]), \
                        patch('credible.service_check.check', return_value={'status': status}), \
                        patch.dict('os.environ', {'GITHUB_OUTPUT': str(github_output)}):
                    self.assertEqual(main(), 0)
                self.assertEqual(read(out)['status'], status)
                self.assertEqual(github_output.read_text().strip(), 'ready=false')


if __name__ == '__main__':
    unittest.main()
