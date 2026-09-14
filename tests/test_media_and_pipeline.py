import copy
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
    def test_rerun_does_not_allocate_or_upload_twice(self):
        config=settings();config['rollout_enabled']=True
        fixed=dt.datetime(2026,9,13,0,tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'output';state=Path(tmp)/'state';root.mkdir()
            reserves=[episode(i) for i in range(9)]
            for ep in reserves: ep['production_version']=3
            save(root/'reserve.json',reserves)
            for ep in reserves: save(root/'episodes'/ep['id']/'episode.json',ep)
            backend=Mock();backend.find.return_value=None
            backend.upload_private.side_effect=['video1','video2','video3']
            model=Mock();model.key='';model.exhausted=False
            with patch('credible.pipeline.settings',return_value=config), \
                 patch('credible.pipeline.now',return_value=fixed), \
                 patch('credible.core.now',return_value=fixed), \
                 patch('credible.pipeline.documents',return_value=({},[])), \
                 patch('credible.discovery.discover',return_value=[]), \
                 patch('credible.pipeline.seed_reserve'), \
                 patch('credible.pipeline.prepare',side_effect=lambda e,*a:e), \
                 patch('credible.pipeline.rendered_checks',return_value={'passed':True}), \
                 patch('credible.pipeline.FreeModel',return_value=model), \
                 patch('credible.pilots.require_pilot_review'), \
                 patch('credible.pipeline.generate_episode',side_effect=RuntimeError('No quota')), \
                 patch('credible.youtube.YouTube',return_value=backend), \
                 patch('credible.state_io.checkpoint'):
                first=run('publish',root,state)
                second=run('publish',root,state)
            self.assertEqual(len(first['slots']),3)
            self.assertEqual(len(second['slots']),3)
            self.assertEqual(backend.upload_private.call_count,3)
            self.assertEqual(len([r for r in read(root/'reserve.json') if r['status']=='ready']),6)


if __name__=='__main__':unittest.main()
