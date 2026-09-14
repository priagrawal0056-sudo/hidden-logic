import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from credible.authored_boards import board
from credible.storyboard import validate_storyboard
from credible.media import punctuated_words, ffmpeg
from credible.evidence import FreeModel
from credible.pipeline import settings, prepare
from credible.pilots import require_pilot_review, production_fingerprint
from credible.core import save
from credible.quality import editorial_checks


class EditorialTests(unittest.TestCase):
    def test_clean_index_does_not_skip_retry_of_failed_state_push(self):
        import os
        import subprocess
        from credible.state_io import checkpoint
        with tempfile.TemporaryDirectory() as tmp:
            original=os.getcwd()
            try:
                os.chdir(tmp)
                save('state/credible/production.json',{'slots':{}})
                def git(args,**kwargs):
                    if args[1]=='push': raise subprocess.CalledProcessError(1,args)
                    return subprocess.CompletedProcess(args,0,stdout='')
                with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','GITHUB_REF_NAME':'test'}), patch('subprocess.run',side_effect=git) as run:
                    with self.assertRaises(subprocess.CalledProcessError):checkpoint('empty')
                    self.assertTrue(any(call.args[0][1]=='push' for call in run.call_args_list))
            finally:os.chdir(original)

    def test_missing_cached_video_rebuilds_without_resynthesizing_voice(self):
        from credible.seeds import build_recipe, RECIPES
        from credible.authored_evidence import PASSAGES
        from credible.core import read, file_hash
        ep=build_recipe(RECIPES[0],{'url':'https://example.org','publisher':'test','pillar':'technology'},
            {'text':' '.join(PASSAGES['gps']),'retrieved_at':'2026-09-14'})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def voice(episode,folder,config):
                (folder/'voice.mp3').write_bytes(b'cached voice')
                episode.update(duration=24,scenes=[],captions=[],voice={},
                    assets=[{'path':'voice.mp3','sha256':file_hash(folder/'voice.mp3')}])
                return episode
            with patch('credible.pipeline.synthesize',side_effect=voice) as synth, \
                 patch('credible.pipeline.timeline_checks'), patch('credible.pipeline.render') as render, \
                 patch('credible.pipeline.rendered_checks',side_effect=[{'passed':True},ValueError('Rendered video missing'),{'passed':True}]):
                first=prepare(ep,root,settings())
                second=prepare(first,root,settings())
                self.assertEqual(synth.call_count,1)
                self.assertEqual(render.call_count,2)
                self.assertEqual(second['status'],'ready')

    def test_keyword_in_wrong_source_does_not_verify_mechanism(self):
        from credible.seeds import build_recipe, RECIPES
        with self.assertRaisesRegex(ValueError,'supporting passage missing'):
            build_recipe(RECIPES[0],{'url':'https://example.org','publisher':'test','pillar':'technology'},
                         {'text':'Buildings are often tall.','retrieved_at':'2026-09-14'})

    def test_car_path_stays_on_circular_lane(self):
        import math
        for scene in board('roundabout'):
            car=scene['objects'][4]
            for x,y in car['motion_path']:
                self.assertAlmostEqual(math.hypot(x+14-250,y+10-418),94)
        car=board('roundabout')[3]['objects'][3]
        self.assertEqual(car['motion_start'],.55)
    def test_punctuation_and_contractions_survive_timings(self):
        words=[{'text':w,'start':i,'end':i+.8} for i,w in enumerate(['New','price','Same','stripes','It','doesn','t','change'])]
        result=punctuated_words("New price. Same stripes. It doesn't change.",words)
        self.assertEqual([r['text'] for r in result],['New','price.','Same','stripes.','It',"doesn't",'change.'])
        self.assertEqual(result[5]['start'],5)
        self.assertEqual(result[5]['end'],6.8)

    def test_extra_or_changed_narration_rejected(self):
        with self.assertRaisesRegex(ValueError,'mismatch'):
            punctuated_words('New price.',[{'text':'different','start':0,'end':1}])

    def test_movement_outside_safe_area_rejected(self):
        plan=board('gps');plan[0]['objects'][0]['move']=[900,0]
        with self.assertRaisesRegex(ValueError,'safe area'):validate_storyboard(plan)

    def test_repeated_visual_with_new_headings_rejected(self):
        plan=[copy.deepcopy(board('dns')[0]) for _ in range(4)]
        for n,s in enumerate(plan): s['heading']=str(n)
        with self.assertRaisesRegex(ValueError,'sameness'):validate_storyboard(plan)

    def test_long_visual_label_rejected(self):
        plan=board('dns');plan[0]['objects'][1]['text']='LongWord'*70
        with self.assertRaisesRegex(ValueError,'overflow'):validate_storyboard(plan)

    def test_production_directions_cannot_leak_into_narration(self):
        ep={'beats':['[pause] Watch this.'],'title':'A thing'}
        with self.assertRaisesRegex(ValueError,'instruction'):editorial_checks(ep)

    def test_authored_visuals_all_validate(self):
        for key in ('gps','bluetooth','dns','roundabout','baggage','screening','unit','barcode','payment'):
            self.assertTrue(validate_storyboard(board(key)),key)

    def test_403_does_not_retry_or_expose_key(self):
        model=FreeModel(settings());model.key='secret-do-not-log'
        response=Mock(ok=False,status_code=403)
        response.json.return_value={'error':{'message':'Your API key was reported as leaked: secret-do-not-log'}}
        with patch('requests.post',return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError,'key_blocked_as_leaked') as error:model.call('test')
            self.assertNotIn(model.key,str(error.exception))
            with self.assertRaises(RuntimeError):model.call('retry')
            self.assertEqual(post.call_count,1)

    def test_old_cache_cannot_bypass_new_production_version(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'migration'):
                prepare({'id':'old','render_version':2},Path(root),settings())

    def test_review_requires_six_current_approved_pilots(self):
        config=settings()
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'review.json'
            review={'production_fingerprint':production_fingerprint(config),'reviewer':'test reviewer',
                    'reviewed_at':'2026-09-14','pilots':[{'id':str(i),'pillar':('technology','travel','shopping')[i%3],
                    'video_sha256':'a'*64,'approved':True} for i in range(6)]}
            save(p,review);self.assertTrue(require_pilot_review(config,p))
            review['pilots'][0]['approved']=False;save(p,review)
            with self.assertRaisesRegex(ValueError,'Two approved'):require_pilot_review(config,p)
            review['production_fingerprint']='stale';save(p,review)
            with self.assertRaisesRegex(ValueError,'matching'):require_pilot_review(config,p)
