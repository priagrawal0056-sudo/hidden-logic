import asyncio
import json
import string
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import assemble
import scriptgen
import tts
import visuals

class OriginalEditorialTests(unittest.TestCase):
    def test_long_sentence_is_not_split_and_script_supplies_punctuation(self):
        words = [{'word':'Wait','start':0,'end':.3},
                 {'word':'here','start':.4,'end':5.11},
                 {'word':'Then','start':5.5,'end':5.8},
                 {'word':'follow','start':5.9,'end':6.2}]
        durations = assemble.sentence_segments(words, 'Wait here. Then follow.')
        self.assertEqual(len(durations), 2)
        self.assertAlmostEqual(durations[0], 5.23)
        self.assertAlmostEqual(sum(durations), 7)

    def test_mismatched_or_estimated_narration_blocks_cuts(self):
        words = [{'word':'Hello','start':0,'end':1}]
        with self.assertRaisesRegex(ValueError, 'transcript'):
            assemble.sentence_segments(words, 'Hello there.')
        words[0]['estimated'] = True
        with self.assertRaisesRegex(ValueError, 'Measured'):
            assemble.sentence_segments(words, 'Hello.')

    def test_contraction_tokenization_and_decimal_do_not_create_extra_cuts(self):
        words = [{'word':w,'start':i,'end':i+.6} for i,w in enumerate(['It',"isn't",'1.5','yet','Follow'])]
        durations = assemble.sentence_segments(words, "It isn't 1.5 yet. Follow.")
        self.assertEqual(len(durations), 2)

    def test_fractional_frame_rounding_never_moves_a_cut_early(self):
        durations = [1.011, 2.012, 3.013, .8]
        frames = assemble._segment_frames(durations)
        for count in range(1, len(frames)+1):
            actual = sum(frames[:count])/30
            expected = sum(durations[:count])
            self.assertGreaterEqual(actual + 1e-9, expected)
            self.assertLess(actual - expected, 1/30 + 1e-9)

    def test_mismatched_scene_lengths_are_not_silently_rescaled(self):
        with tempfile.TemporaryDirectory() as folder:
            timings = Path(folder)/'words.json'
            timings.write_text(json.dumps([{'word':'end','start':5,'end':5.2}]))
            for durations in ([2], [2, 3], [float('nan'), 2]):
                with self.assertRaises(ValueError):
                    assemble.assemble(['a.mp4','b.mp4'],'voice.mp3',str(timings),'captions.ass','out.mp4',seg_seconds=durations)

    def test_writer_and_review_templates_format_with_existing_interface(self):
        for name in ['WRITE_PROMPT','REVIEW_PROMPT','REVISE_PROMPT']:
            value=getattr(scriptgen,name)
            fields={field:'example' for _,field,_,_ in string.Formatter().parse(value) if field}
            self.assertIn('script',value.format(**fields))
        self.assertIn('answer_clarity_score',scriptgen.REVIEW_PROMPT)
        self.assertNotIn('delayed_reveal_score',scriptgen.REVIEW_PROMPT)

    def test_original_voice_is_stable_and_punctuation_is_preserved(self):
        self.assertEqual({tts.pick_voice() for _ in range(20)},{tts.DEFAULT_VOICE})
        text='Scan it. The price changes but the barcode stays.'
        self.assertEqual(tts._add_prosody(text),text)
        self.assertEqual(tts.SPEECH_SPEED,1.0)

    def test_edge_requests_measured_boundaries_and_configured_rate(self):
        class Speech:
            async def stream(self):
                yield {'type':'audio','data':b'audio'}
                yield {'type':'WordBoundary','text':'Scan','offset':1000000,'duration':2000000}
        with tempfile.TemporaryDirectory() as folder, patch.object(tts,'_TTS_CFG',{'edge_voice_rate':'+2%'}), patch.object(tts.edge_tts,'Communicate',return_value=Speech()) as call:
            _,words=asyncio.run(tts._synth('Scan.',str(Path(folder)/'voice.mp3'),tts.DEFAULT_VOICE))
            self.assertEqual(call.call_args.kwargs,{'rate':'+2%','boundary':'WordBoundary'})
            self.assertAlmostEqual(words[0]['start'],.1)

    def test_unscored_footage_is_not_a_perfect_match(self):
        with patch.object(visuals,'_search_all',return_value=[{'id':'one'}]):
            candidates,_=visuals._search_and_score({},None,'scanner','','','barcode',True,8)
        self.assertEqual(candidates[0]['score'],0)
        self.assertEqual(candidates[0]['assessment_status'],'unverified')

    def test_default_assembler_preserves_shot_order_without_synthetic_impacts(self):
        with tempfile.TemporaryDirectory() as folder:
            timings=Path(folder)/'words.json'
            timings.write_text(json.dumps([{'word':'end','start':5,'end':5.2}]))
            response=SimpleNamespace(returncode=0,stdout='30',stderr='')
            with patch.object(assemble.shutil,'which',side_effect=lambda name:name), patch.object(assemble.subprocess,'run',return_value=response) as run, patch.object(assemble,'_make_sfx') as sfx, patch.object(assemble,'_normalize_loudness'):
                assemble.assemble(['a.mp4','b.mp4','c.mp4'],'voice.mp3',str(timings),'captions.ass','preview.mp4',seg_seconds=[2,2,2])
                command=next(c.args[0] for c in run.call_args_list if '-filter_complex' in c.args[0])
                graph=command[command.index('-filter_complex')+1]
                self.assertIn('[2:v]trim=',graph)
                self.assertNotIn('zoompan',graph)
                self.assertNotIn('vignette',graph)
                sfx.assert_not_called()

    def test_failed_gemini_does_not_silently_become_edge(self):
        with patch.object(tts,'_try_gemini_tts',return_value=None), patch.object(tts,'_synth') as edge:
            with self.assertRaisesRegex(RuntimeError,'substitution disabled'):
                tts.synthesize('A short test.','voice.mp3','words.json',engine='auto')
            edge.assert_not_called()

    def test_repeated_background_path_is_rejected_before_render(self):
        with self.assertRaisesRegex(ValueError,'distinct footage'):
            assemble.assemble(['same.mp4','same.mp4'],'voice.mp3','words.json','captions.ass','out.mp4')

    def test_missing_scene_is_not_filled_with_an_earlier_clip(self):
        with tempfile.TemporaryDirectory() as folder:
            def download(video,path):
                Path(path).write_bytes(b'first clip');return True
            with patch.object(visuals,'_load_used',return_value=set()), patch.object(visuals,'_save_used'), patch.object(visuals,'_detect_concept',return_value=None), patch.object(visuals,'_search_and_score',side_effect=[([{'id':'first'}],[]),([],[])]), patch.object(visuals,'_download',side_effect=download), patch.object(visuals.time,'sleep'):
                with self.assertRaisesRegex(RuntimeError,'Missing distinct footage for scene 2'):
                    visuals.fetch_backgrounds('test',['scanner','price'],folder,count=2)

    def test_auth_failure_stops_tts_without_trying_other_models(self):
        response=SimpleNamespace(status_code=403)
        with patch.object(tts.requests if hasattr(tts,'requests') else __import__('requests'),'post',return_value=response) as post:
            self.assertIsNone(tts._try_gemini_tts('test','voice.mp3','words.json','test-key'))
            self.assertEqual(post.call_count,1)
