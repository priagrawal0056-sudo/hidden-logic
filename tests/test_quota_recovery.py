import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import service_limits


class QuotaRecoveryTests(unittest.TestCase):
    def test_only_explicit_quota_ids_determine_limit_kind(self):
        for quota_id,expected in [('GenerateRequestsPerDayPerProject','daily'),
                                   ('GenerateRequestsPerMinutePerProject','per_minute'),
                                   ('unspecified',None)]:
            response=Mock()
            response.json.return_value={'error':{'details':[
                {'violations':[{'quotaId':quota_id}]},{'retryDelay':'32.5s'}]}}
            with service_limits.session():
                with self.assertRaises(service_limits.ServiceUnavailable) as caught:
                    service_limits.observe(429,response)
                self.assertEqual(caught.exception.limit_kind,expected)
                self.assertEqual(caught.exception.retry_after,32.5)
                with self.assertRaises(service_limits.ServiceUnavailable) as later:service_limits.check()
                self.assertEqual(later.exception.limit_kind,expected)
        self.assertFalse(service_limits.blocked())

    def test_preview_reuses_reviewed_draft_after_media_failure(self):
        from credible.single import build
        topic={'topic_id':'test','category':'home'}
        episode={'id':'test-episode','beats':['A.','B.','C.','D.'],'evidence':[]}
        model=Mock()
        with tempfile.TemporaryDirectory() as directory, \
             patch('credible.single.settings',return_value={'production_version':4}), \
             patch('credible.single.load_config',return_value={'gemini_api_key':'test','pexels_api_key':'test'}), \
             patch('credible.single.FreeModel',return_value=model), \
             patch('credible.pipeline.history',return_value=[]), \
             patch('credible.single.load_bank',return_value=[]), \
             patch('credible.single.shortlist',return_value=[topic]), \
             patch('credible.single.sources_for',return_value=[]), \
             patch('credible.single.documents',return_value=({},[])), \
             patch('credible.single.generate_episode',return_value=episode) as writer, \
             patch('credible.single.script_checks'), \
             patch('credible.evidence.verify_support') as evidence, \
             patch('credible.single.prepare',side_effect=[RuntimeError('quota'),episode]) as prepare:
            root=Path(directory)
            with self.assertRaises(RuntimeError):build('home',root)
            self.assertTrue((root/'draft.json').is_file())
            self.assertEqual(build('home',root),episode)
            writer.assert_called_once()
            evidence.assert_called_once_with([], {})
            self.assertEqual(prepare.call_count,2)
            self.assertFalse(json.loads((root/'result.json').read_text())['published'])
