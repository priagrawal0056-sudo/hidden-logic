"""Exit policy tests use a real CLI process and saved recovery state, no live quota."""
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import service_limits
from credible import pipeline, single
from credible.core import read, save
from tests import test_pipeline_recovery as fixtures


def exhausted(*args):
    response=Mock()
    response.json.return_value={'error':{'details':[{
        'violations':[{'quotaId':'GenerateRequestsPerDayPerProject'}]}]}}
    service_limits.observe(429,response)


class QuotaExitTests(unittest.TestCase):
    def test_real_cli_process_exits_zero_and_preserves_unfinished_episode(self):
        program='''
import contextlib, sys
from pathlib import Path
from unittest.mock import patch
from credible.pipeline import main
from tests import test_pipeline_recovery as fixtures
from tests.test_quota_exit import exhausted
with fixtures.pipeline_dependencies([fixtures.brief(0)],
        lambda *a, topic, **k: fixtures.draft(topic), exhausted, videos=1):
    with contextlib.redirect_stdout(sys.__stdout__), patch('sys.argv',
            ['pipeline','--mode','preview','--output',sys.argv[1]]):
        main()
'''
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',program,directory],
                                  cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)
            self.assertIn('Gemini daily quota exhausted',result.stdout)
            self.assertNotIn('Traceback',result.stderr)
            report=read(Path(directory)/'run-report.json')
            self.assertEqual(report['status'],'deferred_quota')
            self.assertEqual(report['completed_slots'],0)
            self.assertEqual(report['pending_episodes'],1)
            self.assertEqual(report['errors'],[])
            self.assertEqual(len(report['deferred_slots']),1)
            state=read(Path(directory)/'preview-state'/'production.json')
            self.assertIn('topic-0',state['pending_episodes'])
            self.assertEqual(state['topics']['topic-0']['status'],'reserved')
            # A later run resumes the saved draft, rather than consuming it.
            with fixtures.pipeline_dependencies([],Mock(side_effect=AssertionError('Do not rewrite')),
                    lambda episode,*a:{**episode,'status':'ready'},videos=1):
                pipeline.run('preview',Path(directory))
            self.assertEqual(read(Path(directory)/'run-report.json')['status'],'ready')

    def test_recovered_source_failures_are_warnings_when_quota_defers_run(self):
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0)],lambda *a,topic,**k:fixtures.draft(topic),exhausted,videos=1) as mocks:
            mocks['credible.pipeline.documents'].return_value=({},[
                {'source':'gps','error':'HTTPError','fallback':'reviewed_snapshot'}])
            with patch('sys.argv',['pipeline','--output',directory]):
                pipeline.main()
            report=read(Path(directory)/'run-report.json')
            self.assertEqual(report['errors'],[])
            self.assertTrue(report['warnings'])
            self.assertEqual(report['status'],'deferred_quota')

    def test_unrelated_failure_is_not_hidden_by_later_quota(self):
        def writer(*args,topic,**kwargs):
            if topic['topic_id']=='topic-0':raise ValueError('Unsupported claim')
            return fixtures.draft(topic)
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0),fixtures.brief(1)],writer,exhausted,videos=1):
            with patch('sys.argv',['pipeline','--output',directory]), self.assertRaises(SystemExit) as error:
                pipeline.main()
            self.assertEqual(error.exception.code,1)
            report=read(Path(directory)/'run-report.json')
            self.assertEqual(report['status'],'incomplete')
            self.assertTrue(any('Unsupported claim' in row.get('error','') for row in report['errors']))

    def test_authentication_failure_does_not_get_success_exit(self):
        for status in (401,403):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                    [fixtures.brief(0)],lambda *a,topic,**k:fixtures.draft(topic),
                    lambda *a:service_limits.observe(status),videos=1):
                with patch('sys.argv',['pipeline','--output',directory]), self.assertRaises(SystemExit) as error:
                    pipeline.main()
                self.assertEqual(error.exception.code,1)
                self.assertEqual(read(Path(directory)/'run-report.json')['status'],'incomplete')

    def test_report_write_failure_propagates_instead_of_exiting_successfully(self):
        def persist(path,value):
            if Path(path).name=='run-report.json':raise OSError('Disk full')
            save(path,value)
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0)],lambda *a,topic,**k:fixtures.draft(topic),exhausted,videos=1), \
                patch('credible.pipeline.save',side_effect=persist), \
                patch('sys.argv',['pipeline','--output',directory]):
            with self.assertRaisesRegex(OSError,'Disk full'):pipeline.main()

    def test_publish_upload_failure_wins_over_generation_quota(self):
        def writer(*args,topic,**kwargs):
            if topic['topic_id']=='topic-1':exhausted()
            return fixtures.draft(topic)
        def ready(episode,root,config):
            save(root/'episodes'/episode['id']/'episode.json',episode)
            return {**episode,'status':'ready'}
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies(
                [fixtures.brief(0),fixtures.brief(1)],writer,ready,videos=2) as mocks, \
                patch('credible.pilots.require_pilot_review'),patch('credible.state_io.checkpoint'), \
                patch('credible.youtube.YouTube'),patch('credible.youtube.deliver',side_effect=RuntimeError('Upload failed')):
            mocks['credible.pipeline.settings'].return_value['rollout_enabled']=True
            root=Path(directory)
            with self.assertRaises(pipeline.DailyIncompleteError) as error:
                pipeline.run('publish',root,root/'state')
            self.assertNotIsInstance(error.exception,pipeline.QuotaDeferred)
            self.assertEqual(read(root/'run-report.json')['status'],'incomplete')

    def test_single_preview_quota_is_deferred_without_claiming_publication(self):
        with tempfile.TemporaryDirectory() as directory, patch('sys.argv',['single','--output',directory]), \
                patch('credible.single.build',side_effect=service_limits.ServiceUnavailable(429,'daily')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            single.main()
            self.assertIn('Gemini daily quota exhausted',output.getvalue())
            report=read(Path(directory)/'result.json')
            self.assertEqual(report['status'],'deferred_quota')
            self.assertFalse(report['published'])

    def test_quota_message_does_not_invent_daily_limits_for_unspecified_429(self):
        for kind,phrase in [('daily','daily quota exhausted'),('per_minute','per-minute rate limit reached'),
                            (None,'rate limit or quota exhausted')]:
            quota=service_limits.quota_deferral(service_limits.ServiceUnavailable(429,kind))
            self.assertIn(phrase,service_limits.quota_message(quota))
        self.assertIsNone(service_limits.quota_deferral(RuntimeError('Gemini HTTP 429')))

    def test_bootstrap_defers_on_quota_but_keeps_partial_ready_progress(self):
        def quota_seed(root,config,docs,catalog,state,reserve,errors,limit):
            try:exhausted()
            except service_limits.ServiceUnavailable as exc:errors.append(pipeline._issue(exc,candidate='seed'))
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies([],Mock(),Mock()) as mocks:
            mocks['credible.pipeline.seed_reserve'].side_effect=quota_seed
            with patch('sys.argv',['pipeline','--mode','bootstrap','--output',directory]):pipeline.main()
            self.assertEqual(read(Path(directory)/'run-report.json')['status'],'deferred_quota')
        def partial_seed(root,config,docs,catalog,state,reserve,errors,limit):
            reserve.append({'id':'one','status':'ready'})
            save(root/'reserve.json',reserve)
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies([],Mock(),Mock()) as mocks:
            mocks['credible.pipeline.seed_reserve'].side_effect=partial_seed
            with patch('sys.argv',['pipeline','--mode','bootstrap','--output',directory]):pipeline.main()
            self.assertEqual(read(Path(directory)/'run-report.json')['status'],'partial_ready')

    def test_bootstrap_save_failure_cannot_be_masked_by_quota(self):
        def failed_seed(root,config,docs,catalog,state,reserve,errors,limit):
            try:exhausted()
            except service_limits.ServiceUnavailable as exc:errors.append(pipeline._issue(exc,candidate='seed'))
            errors.append(pipeline._issue(OSError('Reserve save failed'),candidate='seed'))
        with tempfile.TemporaryDirectory() as directory, fixtures.pipeline_dependencies([],Mock(),Mock()) as mocks:
            mocks['credible.pipeline.seed_reserve'].side_effect=failed_seed
            with patch('sys.argv',['pipeline','--mode','bootstrap','--output',directory]), self.assertRaises(SystemExit) as error:
                pipeline.main()
            self.assertEqual(error.exception.code,1)


if __name__=='__main__':unittest.main()
