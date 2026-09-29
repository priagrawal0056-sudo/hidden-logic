"""Run-local request diagnostics must explain quota use without leaking secrets."""
import json
import unittest
from unittest.mock import Mock, patch

import requests

import service_limits


def response(status, details=None):
    result = Mock(status_code=status)
    result.json.return_value = {'error': {'message': 'private-key project/123456789',
                                         'details': details or []}}
    return result


class RequestAccountingTests(unittest.TestCase):
    def test_success_retries_and_consumers_are_counted_separately(self):
        replies = [response(503), response(200)]
        with service_limits.session(), patch('service_limits.time.sleep'):
            service_limits.request_with_retry(lambda: replies.pop(0),
                                             model='gemini-2.5-flash', stage='writing')
            service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
            service_limits.observe(200)
            service_limits.request_with_retry(lambda: response(200),
                                             model='gemini-2.5-flash', stage='footage_review')
            report = service_limits.report()
        self.assertEqual(report['total_attempts'], 4)
        self.assertEqual(report['requests'], [
            {'model': 'gemini-2.5-flash', 'stage': 'footage_review', 'status': '200', 'attempts': 1},
            {'model': 'gemini-2.5-flash', 'stage': 'writing', 'status': '200', 'attempts': 1},
            {'model': 'gemini-2.5-flash', 'stage': 'writing', 'status': '503', 'attempts': 1},
            {'model': 'gemini-3.1-flash-tts-preview', 'stage': 'narration', 'status': '200', 'attempts': 1}])

    def test_no_responses_remain_unknown_not_successful(self):
        with service_limits.session(), patch('service_limits.time.sleep'):
            with self.assertRaises(service_limits.TransientServiceError):
                service_limits.request_with_retry(Mock(side_effect=requests.Timeout('private-key')),
                                                 model='gemini-2.5-flash', stage='writing', stop_on_failure=False)
            service_limits.request_with_retry(lambda: response(200),
                                             model='gemini-2.5-flash', stage='writing')
            report = service_limits.report()
        self.assertEqual(report['total_attempts'], 4)
        self.assertEqual([row['status'] for row in report['requests']], ['200', 'no_response'])
        self.assertNotIn('private-key', json.dumps(report))

    def test_blocked_requests_are_not_counted_as_attempts(self):
        with service_limits.session():
            with self.assertRaises(service_limits.ServiceUnavailable):
                service_limits.request_with_retry(lambda: response(429),
                                                 model='gemini-3.1-flash-tts-preview', stage='narration')
            send = Mock()
            with self.assertRaises(service_limits.ServiceUnavailable):
                service_limits.request_with_retry(send, model='gemini-2.5-flash', stage='writing')
            send.assert_not_called()
            self.assertEqual(service_limits.report()['total_attempts'], 1)
            self.assertEqual(service_limits.report()['requests'][0]['status'], '429')
            self.assertEqual(service_limits.quota_deferral()['model'], 'gemini-3.1-flash-tts-preview')

    def test_provider_model_quota_and_cap_survive_later_stop_checks(self):
        details = [{'violations': [{
            'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier',
            'quotaMetric': 'generativelanguage.googleapis.com/generate_content_free_tier_requests',
            'quotaValue': '10',
            'quotaDimensions': {'model': 'gemini-3.1-flash-tts-preview', 'project': '123456789'},
            'description': 'private-key', 'subject': 'projects/123456789'}]},
            {'retryDelay': '38s'}]
        with service_limits.session():
            with self.assertRaises(service_limits.ServiceUnavailable) as caught:
                service_limits.request_with_retry(lambda: response(429, details),
                                                 model='gemini-3.1-flash-tts-preview', stage='narration')
            quota = service_limits.quota_deferral(caught.exception)
            with self.assertRaises(service_limits.ServiceUnavailable) as later:
                service_limits.check()
            self.assertEqual(service_limits.quota_deferral(later.exception), quota)
            self.assertEqual(service_limits.quota_deferral(), quota)
        self.assertEqual(quota['limit_kind'], 'daily')
        self.assertEqual(quota['stage'], 'narration')
        self.assertEqual(quota['retry_after'], 38)
        self.assertEqual(quota['violations'][0]['quota_value'], 10)
        self.assertNotIn('123456789', json.dumps(quota))
        self.assertNotIn('private-key', json.dumps(quota))

    def test_unrecognized_provider_fields_cannot_become_quota_diagnostics(self):
        details = [{'violations': [None, 'private-key', {
            'quotaId': 'project/123456789 private-key',
            'quotaMetric': 'https://example.org?key=private-key',
            'quotaValue': '123456789', 'quotaDimensions': {'model': 'private-key'}}]}]
        with service_limits.session():
            with self.assertRaises(service_limits.ServiceUnavailable) as caught:
                service_limits.observe(429, response(429, details))
            quota = service_limits.quota_deferral(caught.exception)
        self.assertEqual(quota, {'http_status': 429, 'limit_kind': 'unknown', 'retry_after': None})

    def test_unknown_and_unsafe_labels_are_not_printed(self):
        with service_limits.session():
            service_limits.before_request(model='https://example.org?key=private-key', stage='private-key')
            service_limits.observe(200)
            self.assertEqual(service_limits.report()['requests'], [
                {'model': 'unknown', 'stage': 'unknown', 'status': '200', 'attempts': 1}])

    def test_old_calls_keep_legacy_quota_shape_and_no_model_guess(self):
        with service_limits.session():
            with self.assertRaises(service_limits.ServiceUnavailable) as caught:
                service_limits.observe(429)
            self.assertEqual(service_limits.quota_deferral(caught.exception),
                             {'http_status': 429, 'limit_kind': 'unknown', 'retry_after': None})
        self.assertEqual(service_limits.quota_deferral(service_limits.ServiceUnavailable(429, 'daily', 5)),
                         {'http_status': 429, 'limit_kind': 'daily', 'retry_after': 5})

    def test_session_resets_and_report_is_an_independent_snapshot(self):
        with service_limits.session():
            service_limits.before_request(model='models/gemini-2.5-flash', stage='writing')
            service_limits.observe(200)
            snapshot = service_limits.report()
            snapshot['requests'][0]['attempts'] = 100
            with service_limits.session():
                self.assertEqual(service_limits.report(), {'total_attempts': 0, 'requests': []})
            self.assertEqual(service_limits.report()['total_attempts'], 1)
            self.assertEqual(service_limits.report()['requests'][0]['attempts'], 1)
        self.assertEqual(service_limits.report(), {'total_attempts': 0, 'requests': []})

    def test_double_observe_does_not_double_count(self):
        with service_limits.session():
            service_limits.before_request()
            service_limits.observe(200)
            service_limits.observe(200)
            self.assertEqual(service_limits.report()['total_attempts'], 1)

    def test_exception_keeps_safe_snapshot_after_session_exit(self):
        with service_limits.session():
            with self.assertRaises(service_limits.ServiceUnavailable) as caught:
                service_limits.request_with_retry(lambda: response(429),
                                                 model='gemini-3.1-flash-tts-preview', stage='narration')
        self.assertEqual(service_limits.report()['total_attempts'], 0)
        self.assertEqual(caught.exception.request_report['total_attempts'], 1)
        self.assertEqual(caught.exception.request_report['requests'][0]['status'], '429')

    def test_exception_diagnostics_cannot_inject_unapproved_fields(self):
        error = service_limits.ServiceUnavailable(429, diagnostics={
            'model': 'gemini-2.5-flash', 'stage': 'writing', 'key': 'private-key',
            'project': '123456789', 'violations': [{
                'quota_id': 'GenerateRequestsPerDayPerProject', 'quota_value': 10,
                'project': '123456789', 'message': 'private-key'}]})
        safe = service_limits.quota_deferral(error)
        self.assertEqual(safe['model'], 'gemini-2.5-flash')
        self.assertEqual(safe['violations'], [{'quota_id': 'GenerateRequestsPerDayPerProject', 'quota_value': 10}])
        self.assertNotIn('private-key', json.dumps(safe))
        self.assertNotIn('123456789', json.dumps(safe))

    def test_narration_pacing_cannot_start_four_calls_within_sixty_seconds(self):
        clock = [0.0]
        starts = []
        counts_before_wait = []

        def advance(delay):
            counts_before_wait.append(service_limits.report()['total_attempts'])
            clock[0] += delay

        with service_limits.session(), \
                patch('service_limits.time.monotonic', side_effect=lambda: clock[0]), \
                patch('service_limits.time.sleep', side_effect=advance):
            for _ in range(4):
                service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
                starts.append(clock[0])
                service_limits.observe(200)
            self.assertEqual(service_limits.report()['total_attempts'], 4)
        self.assertEqual(starts, [0.0, 20.5, 41.0, 61.5])
        self.assertEqual(counts_before_wait, [1, 2, 3])

    def test_interleaved_model_calls_preserve_global_and_narration_spacing(self):
        clock = [0.0]

        def advance(delay):
            clock[0] += delay

        with service_limits.session(), \
                patch('service_limits.time.monotonic', side_effect=lambda: clock[0]), \
                patch('service_limits.time.sleep', side_effect=advance):
            service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
            service_limits.observe(200)
            service_limits.before_request(model='gemini-2.5-flash', stage='script_draft')
            service_limits.observe(200)
            self.assertEqual(clock[0], 15)
            service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
            service_limits.observe(200)
            self.assertEqual(clock[0], 30)
            service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
            service_limits.observe(200)
            self.assertEqual(clock[0], 50.5)
            self.assertEqual(service_limits.report()['total_attempts'], 4)


if __name__ == '__main__':
    unittest.main()
