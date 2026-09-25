import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import footage_review
import service_limits
from credible.evidence import FreeModel


def response(value=None, status=200):
    result = Mock(status_code=status, ok=status == 200)
    result.json.return_value = ({'candidates': [{'content': {'parts': [
        {'text': json.dumps(value)}]}}]} if status == 200 else {'error': {}})
    return result


class ServiceResponseTests(unittest.TestCase):
    def model(self, budget=8):
        model = FreeModel({'model': 'gemini-2.5-flash', 'max_model_calls': budget})
        model.key = 'private-test-key'
        return model

    def test_temporary_server_failures_retry_then_return_valid_result(self):
        model = self.model()
        with patch('requests.post', side_effect=[response(status=503), response(status=502),
                                               response({'supported': True})]) as post, \
                patch('service_limits.time.sleep') as sleep:
            self.assertEqual(model.call('review'), {'supported': True})
        self.assertEqual(post.call_count, 3)
        self.assertEqual(model.remaining, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 15])

    def test_exhausted_server_retries_keep_failure_and_consume_real_budget(self):
        model = self.model()
        with patch('requests.post', return_value=response(status=504)) as post, \
                patch('service_limits.time.sleep'):
            with self.assertRaisesRegex(service_limits.TransientServiceError, 'HTTP 504'):
                model.call('draft')
        self.assertEqual(post.call_count, 3)
        self.assertEqual(model.remaining, 5)

    def test_retry_never_exceeds_writer_budget(self):
        model = self.model(budget=1)
        with patch('requests.post', return_value=response(status=503)) as post, \
                patch('service_limits.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 503'):
                model.call('draft')
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    def test_authentication_and_quota_are_not_retried(self):
        for status in (401, 403, 429):
            with self.subTest(status=status), service_limits.session(), \
                    patch('requests.post', return_value=response(status=status)) as post, \
                    patch('service_limits.time.sleep') as sleep:
                with self.assertRaises(service_limits.ServiceUnavailable):
                    self.model().call('draft')
                with self.assertRaises(service_limits.ServiceUnavailable):
                    service_limits.request_with_retry(lambda: response({}))
                self.assertEqual(post.call_count, 1)
                sleep.assert_not_called()

    def test_writer_list_is_repaired_once_without_trusting_its_contents(self):
        model = self.model()
        with patch('requests.post', side_effect=[response([{'supported': True}]),
                                               response({'supported': False})]) as post:
            self.assertEqual(model.call('review'), {'supported': False})
        self.assertEqual(post.call_count, 2)
        self.assertIn('not a list', post.call_args.kwargs['json']['contents'][0]['parts'][0]['text'])
        self.assertEqual(model.remaining, 6)

    def test_repeated_list_responses_are_controlled_failure(self):
        with patch('requests.post', return_value=response([{'supported': True}])) as post:
            with self.assertRaises(service_limits.ResponseFormatError):
                self.model().call('review')
        self.assertEqual(post.call_count, 2)

    def test_malformed_provider_envelopes_never_raise_attribute_errors(self):
        for envelope in ([], {'candidates': []}, {'candidates': [None]},
                         {'candidates': [{'content': []}]},
                         {'candidates': [{'finishReason': 'MAX_TOKENS'}]}):
            with self.subTest(envelope=envelope):
                bad = Mock()
                bad.json.return_value = envelope
                with self.assertRaises(service_limits.ResponseFormatError):
                    service_limits.response_object(bad)

    def assess(self, responses, directory):
        path = Path(directory) / 'clip.mp4'
        with patch('footage_review._unavailable', None), \
                patch('footage_review._ffmpeg', return_value='ffmpeg'), \
                patch('footage_review.subprocess.run', return_value=Mock(stdout=b'frame')), \
                patch('footage_review.requests.post', side_effect=responses) as post, \
                patch('service_limits.time.sleep'):
            result = footage_review.assess(path, 4, 'The scanner reads the code.', [], 'private-test-key')
            return result, post.call_count

    def test_live_list_verdict_regression_cannot_become_an_attribute_error_or_pass(self):
        # Reproduces the live bluetooth failure: the JSON root was an array, so
        # the former result.get(...) crashed before recording any assessment.
        invalid = [{'relevant': True, 'exposure_ok': True, 'distinct': True,
                    'description': 'An unverified model response.'}]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(service_limits.ResponseFormatError, 'malformed frame-review response') as error:
                self.assess([response(invalid), response(invalid)], directory)
            self.assertNotIsInstance(error.exception, footage_review.RejectedFootage)
            self.assertFalse(list(Path(directory).glob('*.review.json')))

    def test_frame_list_repair_requires_a_fresh_valid_assessment(self):
        valid = {'relevant': True, 'exposure_ok': True, 'distinct': True,
                 'description': 'Hands scan a clearly visible product barcode.'}
        with tempfile.TemporaryDirectory() as directory:
            result, calls = self.assess([response([valid]), response(valid)], directory)
        self.assertEqual(calls, 2)
        self.assertEqual(result['assessment_status'], 'sampled_frames_checked')

    def test_false_verdict_is_rejected_without_format_retry_and_saved(self):
        rejected = {'relevant': False, 'exposure_ok': True, 'distinct': True,
                    'description': 'The clip shows an unrelated street.'}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(footage_review.RejectedFootage, 'relevant'):
                self.assess([response(rejected)], directory)
            saved = json.loads((Path(directory) / 'clip.mp4.review.json').read_text())
            self.assertFalse(saved['assessment']['relevant'])
            self.assertNotIn('private-test-key', json.dumps(saved))

    def test_boolean_strings_and_missing_fields_never_count_as_passes(self):
        for invalid in ({'relevant': 'true', 'exposure_ok': True, 'distinct': True, 'description': 'Clip'},
                        {'relevant': True, 'exposure_ok': True, 'description': 'Clip'}):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(service_limits.ResponseFormatError, 'malformed frame-review response'):
                    self.assess([response(invalid), response(invalid)], directory)

    def test_frame_server_failure_is_not_an_editorial_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(service_limits.TransientServiceError, 'HTTP 503'):
                self.assess([response(status=503)] * 3, directory)

    def test_editorial_failures_are_not_classified_as_transient_service_failures(self):
        for failure in (ValueError('Unsupported claim'),
                        footage_review.RejectedFootage('Unrelated footage'),
                        RuntimeError('Missing asset')):
            self.assertFalse(service_limits.is_retryable(failure))


if __name__ == '__main__':
    unittest.main()
