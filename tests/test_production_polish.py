import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import assemble
import tts
import captions


class ProductionPolishTests(unittest.TestCase):
    def test_caption_phrase_stays_on_two_lines(self):
        phrase=captions._wrap_ass(['PRODUCT','BARCODE','IDENTIFIES','THE','ITEM'])
        self.assertEqual(phrase, r'PRODUCT BARCODE\NIDENTIFIES THE ITEM')
        self.assertLessEqual(captions._wrap_ass(['A'*15]*5).count(r'\N'), 1)

    def test_authored_shots_reject_reused_source_even_with_different_trims(self):
        with tempfile.TemporaryDirectory() as folder:
            timings=Path(folder)/'words.json'
            timings.write_text(json.dumps([{'word':'end','start':5,'end':5.2}]))
            response=SimpleNamespace(returncode=0,stdout='30',stderr='')
            with patch.object(assemble.shutil,'which',side_effect=lambda name:name), patch.object(assemble.subprocess,'run',return_value=response), patch.object(assemble,'_normalize_loudness'):
                with self.assertRaisesRegex(ValueError,'distinct footage'):
                    assemble.assemble(['same.mp4','same.mp4'],'voice.mp3',str(timings),'captions.ass','out.mp4',seg_seconds=[3,3],shot_plan=[{'source_start':0},{'source_start':2}])
                with self.assertRaisesRegex(ValueError,'distinct footage'):
                    assemble.assemble(['same.mp4','same.mp4'],'voice.mp3',str(timings),'captions.ass','out.mp4',seg_seconds=[3,3],shot_plan=[{'source_start':0},{'source_start':4}])

    def test_renamed_or_recropped_source_is_still_a_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/name) for name in ('a.mp4','b.mp4')]
            for p in paths:
                Path(p).write_bytes(b'identical footage')
            with self.assertRaisesRegex(ValueError,'Renaming'):
                assemble.assemble(paths,'voice.mp3','words.json','captions.ass','out.mp4')
            with self.assertRaisesRegex(ValueError,'source video'):
                assemble.assemble(paths,'voice.mp3','words.json','captions.ass','out.mp4',shot_plan=[{'source_id':'pexels:1'},{'source_id':'pexels:1'}])

    def test_only_long_detected_silence_is_trimmed(self):
        words = [{'start':0,'end':1},{'start':1.4,'end':2},{'start':2.9,'end':3.3}]
        cuts = tts._pause_removals(words, [(1,1.4),(2,2.9)])
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0][0], 2.22)
        self.assertAlmostEqual(cuts[0][1], 2.68)
        self.assertEqual(tts._pause_removals(words, []), [])

    def test_sound_cue_must_match_one_actual_phrase(self):
        words = [{'word':word,'start':i,'end':i+.5} for i,word in enumerate(['The','price','changes'])]
        self.assertEqual(assemble.resolve_sound_cues(words,[{'phrase':'price changes','kind':'chime'}]), [{'time':1,'kind':'chime'}])
        with self.assertRaises(ValueError):
            assemble.resolve_sound_cues(words,[{'phrase':'barcode scans','kind':'scan'}])

    def test_loudness_failure_is_visible(self):
        with patch.object(assemble,'_measure_loudness',side_effect=RuntimeError('no audio')):
            with self.assertRaisesRegex(RuntimeError,'audio verification'):
                assemble._normalize_loudness('missing.mp4')

    def test_caption_long_words_are_fitted_in_safe_region(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/'words.json', Path(folder)/'captions.ass'
            source.write_text(json.dumps([{'word':'internationalization','start':0,'end':1}]))
            captions.build_ass(str(source),str(output))
            result = output.read_text()
            self.assertIn('110,210,1240',result)
            self.assertIn(r'\fs',result)
            self.assertNotIn(r'\fs88',result)

    def test_gemini_sends_whole_script_once(self):
        import requests
        import service_limits
        response = SimpleNamespace(status_code=403)
        script = 'One connected question? Here is its answer. Follow Hidden Logic.'
        with tempfile.TemporaryDirectory() as directory, patch.object(requests,'post',return_value=response) as post:
            with self.assertRaises(service_limits.ServiceUnavailable):
                tts._try_gemini_tts(script,str(Path(directory)/'voice.mp3'),str(Path(directory)/'words.json'),'test')
            self.assertEqual(post.call_count,1)
            body = post.call_args.kwargs['json']
            self.assertTrue(body['contents'][0]['parts'][0]['text'].endswith(script))

if __name__ == '__main__':
    unittest.main()
