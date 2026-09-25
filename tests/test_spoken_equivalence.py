import json
import unittest
from pathlib import Path
from assemble import sentence_segments
from credible.media import punctuated_words

class SpokenEquivalenceTests(unittest.TestCase):
    def test_actual_rejected_scale_narration_preserves_every_measured_boundary(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/contraction_alignment.json').read_text())
        words=fixture['words'];script=fixture['script']
        self.assertTrue(sentence_segments(words,script))
        result=punctuated_words(script,[{'text':w['word'],'start':w['start'],'end':w['end']} for w in words])
        self.assertEqual(' '.join(w['text'] for w in result),script)
        self.assertEqual(result[0]['text'],"Why's")
        self.assertEqual(result[0]['start'],words[0]['start'])
        self.assertEqual(result[0]['end'],words[1]['end'])
        self.assertEqual(result[-1]['end'],words[-1]['end'])

    def test_safe_expansion_and_changed_meanings(self):
        def measured(text):
            return [{'word':w,'start':i*.3,'end':i*.3+.25} for i,w in enumerate(text.split())]
        self.assertTrue(sentence_segments(measured('You do not need two.'),"You don't need two."))
        self.assertTrue(sentence_segments(measured("You don't need two."),'You do not need two.'))
        for script,actual in [("Why's there a bubble?",'Why was there a bubble?'),
                              ("Why's there a bubble?",'Why has there a bubble?'),
                              ("You don't need two.",'You do need two.'),
                              ('It costs 2 dollars.','It costs 3 dollars.'),
                              ('It works.','It works. Subscribe.')]:
            with self.assertRaises(ValueError):sentence_segments(measured(actual),script)
