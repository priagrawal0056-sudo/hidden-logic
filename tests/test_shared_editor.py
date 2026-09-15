import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import editorial_media
from config_loader import load_config, redacted
from credible.pipeline import settings
from credible.seeds import build_recipe, RECIPES
from credible.authored_evidence import PASSAGES
from credible.quality import script_checks


class SharedEditorTests(unittest.TestCase):
    def test_all_supported_reserves_have_new_style_and_complete_cta(self):
        for recipe in RECIPES:
            key=recipe[0]
            ep=build_recipe(recipe, {'url':'https://example.org','publisher':'test',
                'pillar':'technology' if key in ('gps','dns','bluetooth') else 'shopping' if key in ('unit','barcode','payment') else 'travel'},
                {'text':' '.join(PASSAGES[key]),'retrieved_at':'2026-09-16'}, version=4)
            self.assertTrue(script_checks(ep),key)
            self.assertEqual(ep['production_version'],4)

    def test_diagram_holds_multiple_complete_sentences_without_retiming(self):
        words=[{'word':w,'start':i*2,'end':i*2+1} for i,w in enumerate(['Hook.','Answer.','Explain.','Result.','Follow.'])]
        plan=editorial_media.plan_scenes(words,'Hook. Answer. Explain. Result. Follow.',
                                       {'diagram_target_seconds':5,'diagram_max_seconds':8})
        diagram=next(s for s in plan if s['kind']=='diagram')
        self.assertGreaterEqual(diagram['end']-diagram['start'],5)
        self.assertEqual(plan[0]['kind'],'stock')
        self.assertEqual(plan[-1]['kind'],'stock')
        self.assertAlmostEqual(plan[-1]['end'],words[-1]['end']+.8)
        ends=[w['end'] for w in words]
        for s in plan[:-1]:
            self.assertTrue(any(0 <= s['end']-end <= .13 for end in ends))

    def test_profile_overrides_legacy_caption_and_voice_switches(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'legacy.json'
            p.write_text(json.dumps({'tts_engine':'edge','show_follow_cue':True}))
            cfg=load_config(str(p))
            self.assertEqual(cfg['gemini_voice'],'Orus')
            self.assertEqual(cfg['tts_engine'],'gemini')
            self.assertFalse(cfg['show_follow_cue'])
            self.assertFalse(cfg['allow_voice_fallback'])

    def test_nested_and_pooled_credentials_are_fully_redacted(self):
        self.assertEqual(redacted({'elevenlabs_api_keys':['private'], 'nested':{'token':'private'}}),
                         {'elevenlabs_api_keys':'***','nested':{'token':'***'}})

    def test_scheduler_uses_approved_adapter(self):
        from credible.media import synthesize, render
        with patch('credible.approved.synthesize',return_value='voice') as voice, \
             patch('credible.approved.render',return_value='video') as video:
            ep={'production_version':4}
            self.assertEqual(synthesize(ep,'out',{}),'voice')
            self.assertEqual(render(ep,'out',{}),'video')
            voice.assert_called_once(); video.assert_called_once()
        self.assertEqual(settings()['production_version'],4)
        self.assertFalse(settings()['rollout_enabled'])

    def test_failed_frame_review_is_not_a_pass(self):
        from footage_review import assess
        with self.assertRaisesRegex(RuntimeError,'unverified'):
            assess('clip.mp4',5,'words',[],'')
        response=Mock(ok=False,status_code=429)
        frame=Mock(stdout=b'jpeg')
        with patch('footage_review._unavailable',None), patch('footage_review.subprocess.run',return_value=frame), patch('footage_review.requests.post',return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError,'HTTP 429'):
                assess('clip.mp4',5,'words',[],'private')
            with self.assertRaisesRegex(RuntimeError,'HTTP 429'):
                assess('another.mp4',5,'words',[],'private')
            self.assertEqual(post.call_count,1)

    def test_original_modules_are_in_pilot_fingerprint(self):
        files={name for name,value in editorial_media.fingerprint()}
        self.assertTrue({'assemble.py','tts.py','captions.py','visuals.py','footage_review.py'} <= files)

    def test_two_line_caption_export_matches_manifest(self):
        import captions
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            words=[{'word':w,'start':i*.3,'end':i*.3+.2} for i,w in enumerate('Product barcode identifies the item.'.split())]
            (p/'timings.json').write_text(json.dumps(words))
            captions.build_ass(str(p/'timings.json'),str(p/'captions.ass'))
            records=editorial_media.caption_records(p/'captions.ass')
            self.assertEqual(' '.join(c['text'] for c in records),'PRODUCT BARCODE IDENTIFIES THE ITEM.')

if __name__=='__main__': unittest.main()
