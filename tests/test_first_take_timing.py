import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import service_limits
import tts
from credible import approved


class FirstTakeTimingTests(unittest.TestCase):
    def target(self):
        return {
            'opening_text': 'Same barcode, on sale? The code identifies the item.',
            'duration_min': 20, 'duration_max': 28,
            'first_answer_max': 6, 'final_hold': .8,
        }

    def test_explicit_target_directs_first_take_without_changing_words_or_voice(self):
        direction = tts._narration_timing_direction({'narration_timing_target': self.target()})
        self.assertIn('about 5.5 seconds', direction)
        self.assertIn('6-second limit', direction)
        self.assertIn(self.target()['opening_text'], direction)
        self.assertIn('one continuous take', direction)
        self.assertIn('0.8-second final hold after speech', direction)
        self.assertIn('Do not add, omit or rewrite words', direction)
        self.assertIn('No artificial speed-up or time stretching', direction)
        self.assertNotIn('previous take', direction)

    def test_legacy_calls_have_no_implicit_timing_contract(self):
        self.assertEqual(tts._narration_timing_direction({}), '')
        self.assertEqual(tts._narration_timing_direction({'duration_min': 20, 'duration_max': 28}), '')

    def test_measured_feedback_takes_precedence_over_initial_target(self):
        direction = tts._narration_timing_direction({
            'narration_timing_target': self.target(),
            'narration_timing_feedback': {
                'previous_duration': 29.5, 'previous_first_answer_end': 6.4,
                'duration_min': 20, 'duration_max': 28, 'first_answer_max': 6,
            },
        })
        self.assertIn('previous take measured 29.50 seconds', direction)
        self.assertIn('6.40 seconds', direction)
        self.assertNotIn('exact opening portion', direction)

    def test_invalid_explicit_targets_fail_before_requesting_audio(self):
        for update in ({'opening_text': ''}, {'duration_min': float('nan')},
                       {'duration_min': 29}, {'first_answer_max': 0},
                       {'duration_max': float('inf')}, {'final_hold': -1}):
            with self.subTest(update=update):
                with self.assertRaisesRegex(ValueError, 'Invalid narration timing target'):
                    tts._narration_timing_direction({'narration_timing_target': {**self.target(), **update}})
        with self.assertRaisesRegex(ValueError, 'Invalid narration timing target'):
            tts._narration_timing_direction({'narration_timing_target': {}})

    def test_approved_adapter_supplies_exact_opening_and_existing_duration_band(self):
        episode = {'beats': [
            'Same barcode, on sale?', 'The code identifies the item.',
            'The store record provides the price.', 'Same barcode, new price.',
        ]}
        words = [{'word': word, 'start': i * .3, 'end': (i + 1) * .3}
                 for i, word in enumerate(' '.join(episode['beats']).split())]
        config = {'duration_min': 21, 'duration_max': 27, 'gemini_voice': 'Orus'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(approved, 'config_for', return_value=config.copy()), \
             patch.object(approved, 'metadata', return_value={'script': ' '.join(episode['beats'])}), \
             patch.object(approved.editorial_media, 'synthesize', return_value=words) as synth, \
             patch.object(approved.editorial_media, 'caption_records', return_value=[]), \
             patch('captions.build_ass'), patch.object(approved, 'file_hash', return_value='test-hash'):
            result = approved.synthesize(episode, Path(directory), config)
        passed_config = synth.call_args.args[2]
        self.assertEqual(passed_config['narration_timing_target'], {
            **self.target(), 'duration_min': 21, 'duration_max': 27,
        })
        self.assertEqual(passed_config['gemini_voice'], 'Orus')
        self.assertNotIn('narration_timing_target', config)
        # Targets guide the take; actual aligned timing is still what QA receives.
        self.assertEqual(result['first_answer_end'], words[8]['end'])

    def test_first_take_keeps_complete_script_and_reports_request_model_and_stage(self):
        script = self.target()['opening_text'] + ' The store record provides the price.'
        model = 'gemini-configured-tts-model'
        response = Mock(status_code=429)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(tts, '_TTS_CFG', {'gemini_voice': 'Orus', 'gemini_tts_model': model,
                                          'narration_timing_target': self.target()}), \
             patch.object(service_limits, 'before_request') as before, \
             patch.object(service_limits, 'observe', side_effect=service_limits.ServiceUnavailable(429, 'daily')), \
             patch('requests.post', return_value=response) as post:
            voice = str(Path(directory) / 'voice.mp3')
            with self.assertRaises(service_limits.ServiceUnavailable):
                tts._try_gemini_tts(script, voice, voice + '.json', 'test-private-key')
            before.assert_called_once_with(model=model, stage='narration')
            post.assert_called_once()
            body = post.call_args.kwargs['json']
            prompt = body['contents'][0]['parts'][0]['text']
            self.assertEqual(prompt.split('\n\nSCRIPT:\n')[1], script)
            self.assertIn('about 5.5 seconds', prompt)
            self.assertEqual(body['generationConfig']['speechConfig']['voiceConfig']
                             ['prebuiltVoiceConfig']['voiceName'], 'Orus')
            diagnostic = json.loads(Path(voice + '.service.json').read_text())
            self.assertEqual(diagnostic['attempts'][0]['limit_kind'], 'daily')


if __name__ == '__main__':
    unittest.main()
