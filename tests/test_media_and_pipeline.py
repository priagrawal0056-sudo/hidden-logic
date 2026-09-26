import copy
import contextlib
import io
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from credible.core import UTC,read,save
from credible.pipeline import run,settings
from credible.quality import timeline_checks
from credible.stock import verify_frames


def episode(index=0):
    text=['You notice the screen changing.',
          'A verified process explains this familiar everyday change clearly.',
          'In this simple illustration, each object moves through the steps shown on the screen so you can follow what happens.',
          'The final result follows from those steps, with no secret motive needed to explain the outcome.']
    from credible.core import tokens
    return {'id':str(index),'claim_id':str(index),'claim':'mechanism '+str(index),
        'subject':str(index),'title':'A useful explanation '+str(index), 'pillar':('technology','travel','shopping')[index%3],
        'format':'process','scene_kind':'process','beats':text,'labels':['A','B','C','D'],
        'evidence_status':'source_checked','editorial_review':{'title_matches':True},
        'duration':24,'status':'ready','scenes':[{'start':i*6,'end':(i+1)*6} for i in range(4)],
        'captions':[{'text':line,'start':i*6,'end':(i+1)*6} for i,line in enumerate(text)],
        'assets':[], 'evidence':[], 'quality':{'passed':True}}


class MediaTests(unittest.TestCase):
    def test_caption_overflow_rejected(self):
        ep=episode();ep['captions'][0]['text']='Unbreakable'*50
        with self.assertRaisesRegex(ValueError,'overflow'):
            timeline_checks(ep,Path('.'),settings())

    def test_narration_caption_mismatch_rejected(self):
        ep=episode();ep['captions']=[{'text':'Wrong words','start':0,'end':24}]
        with self.assertRaisesRegex(ValueError,'mismatch'):
            timeline_checks(ep,Path('.'),settings())

    def test_scene_gap_rejected(self):
        ep=episode();ep['scenes'][1]['start']=7
        with self.assertRaisesRegex(ValueError,'Gap'):
            timeline_checks(ep,Path('.'),settings())

    def test_missing_real_frame_assessment_is_unknown(self):
        model=Mock();model.key=''
        self.assertEqual(verify_frames('missing.mp4','a car',model)['status'],'unverified')

    def test_frame_decode_failure_is_unknown(self):
        model=Mock();model.key='x';model.exhausted=False;model.remaining=2
        with patch('credible.stock.ffmpeg',return_value='missing-encoder'):
            self.assertEqual(verify_frames('missing.mp4','a car',model)['status'],'unverified')


class PipelineTests(unittest.TestCase):
    def test_overdue_slot_does_not_block_new_slots_or_lose_uncertain_identity(self):
        config=settings(); config['rollout_enabled']=True
        fixed=dt.datetime(2026,9,17,0,tzinfo=UTC)
        for old_status in ('prepared','upload_uncertain','uploaded'):
            with self.subTest(status=old_status), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/'output'; state=Path(tmp)/'state'; root.mkdir()
                reserves=[episode(i) for i in range(9)]
                for ep in reserves:
                    ep['production_version']=config['production_version']
                    save(root/'episodes'/ep['id']/'episode.json',ep)
                save(root/'reserve.json',reserves)
                old={**episode(90),'id':'20260916T0700Z','episode_id':'90','status':old_status,
                     'publish_at':'2026-09-16T07:00:00+00:00','slot_index':0}
                if old_status=='uploaded': old['video_id']='existing-private'
                save(state/'production.json',{'slots':{old['id']:old}})
                backend=Mock(); backend.find.return_value=None
                backend.upload_private.side_effect=['new1','new2','new3']
                model=Mock(); model.key=''; model.exhausted=False
                replacements={
                    'credible.pipeline.settings':Mock(return_value=config),
                    'credible.pipeline.now':Mock(return_value=fixed),
                    'credible.core.now':Mock(return_value=fixed),
                    'credible.youtube.now':Mock(return_value=fixed),
                    'credible.pipeline.documents':Mock(return_value=({},[])),
                    'credible.pipeline.seed_reserve':Mock(),
                    'credible.pipeline.prepare':Mock(side_effect=lambda e,*a:e),
                    'credible.pipeline.rendered_checks':Mock(return_value={'passed':True}),
                    'credible.pipeline.FreeModel':Mock(return_value=model),
                    'credible.pilots.require_pilot_review':Mock(),
                    'credible.pipeline.generate_episode':Mock(side_effect=RuntimeError('No quota')),
                    'credible.youtube.YouTube':Mock(return_value=backend),
                    'credible.state_io.checkpoint':Mock()}
                with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
                    for name,obj in replacements.items(): stack.enter_context(patch(name,obj))
                    for retry in range(2):
                        with self.assertRaisesRegex(RuntimeError,'Current slots completed'):
                            run('publish',root,state)
                report=read(root/'run-report.json')
                self.assertEqual(report['completed_slots'],3)
                self.assertEqual(report['status'],'needs_attention')
                self.assertEqual(report['recovery_slots'],[old['id']])
                self.assertEqual(backend.upload_private.call_count,3)
                self.assertEqual(backend.schedule.call_count,3)
                saved=read(state/'production.json')['slots'][old['id']]
                self.assertEqual(saved['status'],old_status)
                self.assertEqual(saved.get('video_id'),old.get('video_id'))

    def test_empty_run_fails_visibly_after_saving_recovery_report(self):
        model=Mock();model.key='';model.exhausted=False
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'preview'
            with patch('credible.pipeline.documents',return_value=({},[])), \
                 patch('credible.pipeline.seed_reserve'), \
                 patch('credible.pipeline.load_bank',return_value=[]), \
                 patch('credible.pipeline.FreeModel',return_value=model):
                with self.assertRaisesRegex(RuntimeError,'Daily target incomplete'):
                    run('preview',root)
            report=read(root/'run-report.json')
            self.assertEqual(report['status'],'incomplete')
            self.assertEqual(report['completed_slots'],0)
            self.assertTrue((root/'preview-state'/'production.json').exists())

    def test_rerun_does_not_allocate_or_upload_twice(self):
        import service_limits
        config=settings();config['rollout_enabled']=True
        fixed=dt.datetime(2026,9,13,0,tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'output';state=Path(tmp)/'state';root.mkdir()
            reserves=[episode(i) for i in range(9)]
            for ep in reserves: ep['production_version']=config['production_version']
            save(root/'reserve.json',reserves)
            for ep in reserves: save(root/'episodes'/ep['id']/'episode.json',ep)
            backend=Mock();backend.find.return_value=None
            backend.upload_private.side_effect=['video1','video2','video3']
            model=Mock();model.key='test';model.exhausted=False
            with patch('credible.pipeline.settings',return_value=config), \
                 patch('credible.pipeline.now',return_value=fixed), \
                 patch('credible.core.now',return_value=fixed), \
                 patch('credible.youtube.now',return_value=fixed), \
                 patch('credible.pipeline.documents',return_value=({},[])), \
                 patch('credible.discovery.discover',return_value=[]), \
                 patch('credible.pipeline.seed_reserve'), \
                 patch('credible.pipeline.prepare',side_effect=lambda e,*a:e), \
                 patch('credible.pipeline.rendered_checks',return_value={'passed':True}), \
                 patch('credible.pipeline.FreeModel',return_value=model), \
                 patch('credible.pilots.require_pilot_review'), \
                 patch('credible.pipeline.generate_episode',side_effect=lambda *a,**k:service_limits.observe(429)), \
                 patch('credible.youtube.YouTube',return_value=backend), \
                 patch('credible.state_io.checkpoint'):
                first=run('publish',root,state)
                second=run('publish',root,state)
            self.assertEqual(len(first['slots']),3)
            self.assertEqual(len(second['slots']),3)
            self.assertEqual(backend.upload_private.call_count,3)
            self.assertEqual(len([r for r in read(root/'reserve.json') if r['status']=='ready']),6)


if __name__=='__main__':unittest.main()
