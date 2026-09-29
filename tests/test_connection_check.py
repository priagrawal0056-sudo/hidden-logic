import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import service_limits
from credible.service_check import check
from credible.single import build
from credible.evidence import EditorialRejected
from tests.test_single_editorial_recovery import dependencies


class ConnectionCheckTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('credible.service_check.time.sleep'))

    def test_missing_or_misformatted_secret_makes_no_request(self):
        for key in ('', ' my-key', 'my-key\n', '"my-key"', 'HL_GEMINI_API_KEY=my-key'):
            get = Mock()
            result = check(key, {'writing': 'gemini-2.5-flash'}, get)
            get.assert_not_called()
            self.assertIn(result['status'], ('missing_secret', 'invalid_secret_format'))
            self.assertEqual(result['generation_requests'], 0)

    def test_paginated_listing_confirms_access_without_claiming_quota(self):
        get = Mock(side_effect=[Mock(status_code=200, json=Mock(return_value={
            'models': [], 'nextPageToken': 'opaque-token'})),
            Mock(status_code=200, json=Mock(return_value={'models': [
                {'name': 'models/gemini-2.5-flash', 'supportedGenerationMethods': ['generateContent']}
            ]}))])
        result = check('private-test-key', {'writing': 'gemini-2.5-flash'}, get)
        self.assertEqual(result['status'], 'connected')
        self.assertIn('quota is not tested', result['message'])
        self.assertEqual(result['generation_requests'], 0)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs['params']['pageToken'], 'opaque-token')
        self.assertNotIn('private-test-key', json.dumps(result))

    def test_good_key_with_missing_model_is_a_configuration_failure(self):
        get = Mock(return_value=Mock(status_code=200, json=Mock(return_value={'models': [
            {'name': 'models/gemini-3.1-flash-tts-preview',
             'supportedGenerationMethods': ['generateContent']}
        ]})))
        result = check('private-test-key', {'writing': 'gemini-2.5-flash'}, get)
        self.assertEqual(result['authentication'], 'accepted')
        self.assertEqual(result['status'], 'model_unavailable')
        self.assertEqual(result['missing_models'], {'writing': 'gemini-2.5-flash'})

    def test_failed_check_never_leaks_body_or_exception(self):
        for get in (Mock(side_effect=requests.ConnectionError('secret-key')),
                    Mock(return_value=Mock(status_code=403, text='secret-key'))):
            result = check('secret-key', {}, get)
            self.assertNotIn('secret-key', json.dumps(result))
            self.assertNotEqual(result['status'], 'connected')

    def test_missing_generation_model_stops_further_api_work(self):
        with service_limits.session(), patch('service_limits.time.sleep'):
            service_limits.before_request(model='gemini-2.5-flash', stage='script_draft')
            with self.assertRaisesRegex(service_limits.ServiceUnavailable, 'configured model unavailable'):
                service_limits.observe(404)
            with self.assertRaises(service_limits.ServiceUnavailable):
                service_limits.before_request(model='gemini-3.1-flash-tts-preview', stage='narration')
            self.assertEqual(service_limits.report()['total_attempts'], 1)
            self.assertIsNone(service_limits.quota_deferral())

    def test_one_candidate_preview_cannot_cycle_through_more_topics(self):
        choices = [{'topic_id': 'one', 'category': 'home'}]
        with tempfile.TemporaryDirectory() as directory, dependencies(
                choices, Mock(side_effect=EditorialRejected('Not supported')), Mock()) as mocks:
            with self.assertRaises(EditorialRejected):
                build('home', Path(directory), max_candidates=1)
            self.assertEqual(mocks['credible.single.shortlist'].call_args.kwargs['n'], 1)
            self.assertEqual(mocks['credible.single.generate_episode'].call_count, 1)
            mocks['credible.single.prepare'].assert_not_called()


if __name__ == '__main__':
    unittest.main()
