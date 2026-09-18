import copy,json,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from credible.storyboard import layout_storyboard,validate_storyboard,draw_storyboard

class LiveLayoutTests(unittest.TestCase):
    def test_actual_failed_drafts_fit_without_changing_label_text(self):
        cases=json.loads((Path(__file__).parent/'fixtures/failed_live_storyboards.json').read_text())
        for case in cases:
            original=copy.deepcopy(case['plan'])
            plan,changes=layout_storyboard(original)
            self.assertTrue(validate_storyboard(plan),case['title'])
            self.assertTrue(changes)
            self.assertEqual(original,case['plan'])
            for before,after in zip(original,plan):
                self.assertEqual([o['text'] for o in before['objects'] if o['type']=='text'],
                                 [o['text'] for o in after['objects'] if o['type']=='text'])
                for phase in (0,.25,.55,.99):
                    self.assertTrue(any(o['type']!='text' and o.get('reveal',0)<=phase<=o.get('until',1) for o in after['objects']))
                    im=Image.new('RGB',(540,960),'#121a24')
                    draw_storyboard(ImageDraw.Draw(im),after,phase)
                    self.assertGreater(len(im.getcolors(540*960)),1)

    def test_unsafe_rotated_shape_is_still_rejected(self):
        cases=json.loads((Path(__file__).parent/'fixtures/failed_live_storyboards.json').read_text())
        plan,_=layout_storyboard(cases[0]['plan'])
        plan[0]['objects'].append({'type':'rect','box':[38,210,100,100],'rotate':45,'color':'ink'})
        with self.assertRaisesRegex(ValueError,'Rotated'):validate_storyboard(plan)

    def test_unreadable_label_is_not_removed_or_shrunk_to_tiny_text(self):
        cases=json.loads((Path(__file__).parent/'fixtures/failed_live_storyboards.json').read_text())
        plan=cases[0]['plan'];plan[0]['objects'].append({'type':'text','box':[100,220,20,20],'text':'ImpossibleLongWord','size':16,'color':'ink'})
        with self.assertRaisesRegex(ValueError,'cannot fit'):layout_storyboard(plan)
