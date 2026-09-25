import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from credible.pipeline import _check_narration_with_retake
from tts import _narration_timing_direction


class NarrationTimingRepairTests(unittest.TestCase):
    def episode(self):
        return {'production_version':4,'duration':29.6,'first_answer_end':5.48,
                'beats':['Same complete script.'],'id':'timing-test'}

    def test_measured_failure_gets_one_take_and_original_audio_is_kept(self):
        initial=self.episode();accepted={**initial,'duration':24.1}
        config={'duration_min':20,'duration_max':28}
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'voice.mp3').write_bytes(b'original take')
            (folder/'timings.json').write_text('[]')
            with patch('credible.pipeline.timeline_checks',side_effect=[ValueError('Measured duration outside trial band'),None]) as checks, \
                 patch('credible.pipeline.synthesize',return_value=accepted) as synth:
                self.assertEqual(_check_narration_with_retake(initial,folder,config),accepted)
                self.assertEqual(checks.call_count,2)
                synth.assert_called_once()
                feedback=synth.call_args.args[2]['narration_timing_feedback']
                self.assertEqual(feedback['previous_duration'],29.6)
                self.assertEqual(feedback['first_answer_max'],6)
                self.assertEqual(synth.call_args.args[0]['beats'],initial['beats'])
            self.assertEqual((folder/'voice.mp3.timing-rejected-1.mp3').read_bytes(),b'original take')
            self.assertEqual(json.loads((folder/'voice.mp3.timing-review.json').read_text())['status'],'passed')

    def test_retake_cannot_hide_caption_failure_or_retry_forever(self):
        for error in ['Caption/narration mismatch','Measured duration outside trial band']:
            with tempfile.TemporaryDirectory() as directory:
                folder=Path(directory)
                with patch('credible.pipeline.timeline_checks',side_effect=[ValueError('First useful answer must finish within six seconds'),ValueError(error)]), \
                     patch('credible.pipeline.synthesize',return_value=self.episode()) as synth:
                    with self.assertRaisesRegex(ValueError,error):
                        _check_narration_with_retake(self.episode(),folder,{'duration_min':20,'duration_max':28})
                    self.assertEqual(synth.call_count,1)
                self.assertEqual(json.loads((folder/'voice.mp3.timing-review.json').read_text())['status'],'rejected')

    def test_unrelated_errors_never_trigger_a_take(self):
        with patch('credible.pipeline.timeline_checks',side_effect=ValueError('Caption overflow')), \
             patch('credible.pipeline.synthesize') as synth:
            with self.assertRaisesRegex(ValueError,'Caption overflow'):
                _check_narration_with_retake(self.episode(),Path('.'),{'duration_min':20,'duration_max':28})
            synth.assert_not_called()

    def test_timing_direction_only_added_for_explicit_measured_feedback(self):
        self.assertEqual(_narration_timing_direction({}),'')
        config={'narration_timing_feedback':{'previous_duration':24.46,
            'previous_first_answer_end':6.04,'duration_min':20,'duration_max':28,'first_answer_max':6}}
        direction=_narration_timing_direction(config)
        self.assertIn('6.04',direction)
        self.assertIn('SAME complete SCRIPT',direction)
        self.assertIn('one continuous take',direction)
        self.assertIn('Do not add, omit or rewrite words',direction)
