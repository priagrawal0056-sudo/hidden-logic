import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, mock_open
from credible.media import punctuated_words
import scriptgen
import tts

class RunFailureTests(unittest.TestCase):
    def test_split_acronym_and_contraction_keep_measured_bounds(self):
        raw = [{'text': w, 'start': i, 'end': i+.8} for i,w in enumerate(['D','N','S','doesnt','move.'])]
        words = punctuated_words("DNS doesn't move.", raw)
        self.assertEqual([w['text'] for w in words], ['DNS', "doesn't", 'move.'])
        self.assertEqual((words[0]['start'],words[0]['end']), (0,2.8))
        self.assertEqual((words[1]['start'],words[1]['end']), (3,3.8))

    def test_missing_or_changed_narration_still_rejected(self):
        for text in ('DNS moves.', 'DNS does not move.'):
            with self.assertRaises(ValueError):
                punctuated_words(text,[{'text':'DNS','start':0,'end':1}])

    def test_discovery_does_not_promote_unknown_previews(self):
        response=Mock()
        response.json.return_value={'models':[{'name':'models/'+n,'supportedGenerationMethods':['generateContent']} for n in ['gemini-3.8-flash','gemini-2.5-flash-lite','gemini-2.5-flash']]}
        with patch.object(scriptgen,'_discovered',None), patch.object(scriptgen.requests,'get',return_value=response):
            self.assertEqual(scriptgen._best_models('test'), ['gemini-2.5-flash','gemini-2.5-flash-lite'])

    def test_alignment_retries_recognition_without_regenerating_voice(self):
        def segments(word):
            return ([SimpleNamespace(words=[SimpleNamespace(word=word,start=0,end=.8)])],None)
        model=Mock(); model.transcribe.side_effect=[segments('wrong'),segments('Hello.')]
        module=SimpleNamespace(WhisperModel=Mock(return_value=model))
        with patch.dict('sys.modules',{'faster_whisper':module}), patch('builtins.open', mock_open()):
            result=tts._align_with_whisper('Hello.','existing.mp3')
        self.assertEqual(result[0]['word'],'Hello.')
        self.assertEqual([c.kwargs['beam_size'] for c in model.transcribe.call_args_list],[1,5])
        self.assertTrue(all('initial_prompt' not in c.kwargs for c in model.transcribe.call_args_list))

    def test_failed_retry_remains_a_failure(self):
        model=Mock();model.transcribe.return_value=([SimpleNamespace(words=[SimpleNamespace(word='wrong',start=0,end=.8)])],None)
        with patch.dict('sys.modules',{'faster_whisper':SimpleNamespace(WhisperModel=Mock(return_value=model))}), patch('builtins.open', mock_open()):
            self.assertIsNone(tts._align_with_whisper('Hello.','existing.mp3'))

    def test_zero_width_word_joins_only_adjacent_measured_phrase(self):
        words=[{'word':'DNS','start':1,'end':1},{'word':'finds','start':1,'end':1.6}]
        fixed=tts._coalesce_measured_words(words)
        self.assertEqual(fixed[0]['word'],'DNS finds')
        self.assertEqual((fixed[0]['start'],fixed[0]['end']),(1,1.6))
        self.assertEqual(fixed[0]['timing_granularity'],'measured_phrase')
        for bad in ([{'word':'end.','start':1,'end':1}],
                    [{'word':'DNS','start':1,'end':1},{'word':'finds','start':2,'end':2.6}]):
            with self.assertRaises(ValueError):tts._coalesce_measured_words(bad)
