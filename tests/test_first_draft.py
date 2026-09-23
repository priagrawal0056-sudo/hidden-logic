import copy
import unittest
from unittest.mock import Mock
from credible.authored_boards import board
from credible.authored_evidence import PASSAGES
from credible.evidence import generate_episode
from credible.approved import metadata
from production_brief import validate,media_metadata,sentences
from editorial_media import plan_scenes


def brief():
    return {'title':'Why Prices Change but Barcodes Do Not',
        'claim':'Ordinary product barcodes identify items whose prices are looked up.',
        'claim_id':'test-lookup','subject':'product-lookup','pillar':'shopping','format':'process',
        'beats':['Same barcode, on sale?', 'The code identifies the item.',
                 "The store's database supplies the price. Update that price, and the same packet scans for less.",
                 'Same barcode, new price. Follow Hidden Logic for more everyday explanations.'],
        'labels':['SAME CODE','IDENTIFY ITEM','PRICE LOOKUP','NEW PRICE'],
        'storyboard':board('barcode'),
        'broll_keywords':['cereal barcode macro','grocery handheld scanner','sale price label close up'],
        'sound_cues':[{'phrase':'Update that price','kind':'chime'}],
        'evidence':[{'claim':'An ordinary barcode identifies an item.','passage_id':'S0P0','scope':'ordinary product barcode'}]}


class FirstDraftTests(unittest.TestCase):
    def test_first_draft_reaches_grounded_review_without_manual_plan(self):
        data=brief()
        verdict={'supported':True,'title_matches':True,'duplicate':False,'visuals_match':True,
                 'natural_script':True,'needs_corroboration':False}
        model=Mock();model.production_version=4;model.remaining=6
        model.call.side_effect=[data,verdict]
        doc={'url':'https://example.org/source','publisher':'Test primary source',
             'text':' '.join(PASSAGES['barcode']),'retrieved_at':'2026-09-16'}
        ep=generate_episode(model,{doc['url']:doc},[],'question_first')
        self.assertEqual(model.call.call_count,2)
        self.assertIn('FIRST draft',model.call.call_args_list[0].args[0])
        meta=metadata(ep)
        self.assertEqual(meta['diagram_sentence_index'],2)
        self.assertEqual(meta['diagram_sentence_count'],2)
        words=[{'word':w,'start':i*.4,'end':i*.4+.3} for i,w in enumerate(meta['script'].split())]
        scenes=plan_scenes(words,meta['script'],{},meta['diagram_sentence_index'],meta['diagram_sentence_count'])
        self.assertEqual([s['kind'] for s in scenes],['stock','stock','diagram','stock','callback'])
        self.assertEqual(scenes[2]['sentence_count'],2)
        self.assertAlmostEqual(scenes[-1]['end'],words[-1]['end']+.8)

    def test_failed_draft_is_given_back_for_targeted_repair(self):
        import copy
        good=brief(); bad=copy.deepcopy(good); bad['storyboard'][0]['heading']='x'*40
        model=Mock();model.production_version=4;model.remaining=6
        model.call.side_effect=[bad,good,{'supported':True,'title_matches':True,'duplicate':False,
            'visuals_match':True,'natural_script':True,'needs_corroboration':False}]
        doc={'url':'https://example.org/source','publisher':'Test primary source',
             'text':' '.join(PASSAGES['barcode']),'retrieved_at':'2026-09-16'}
        generate_episode(model,{doc['url']:doc},[],'question_first')
        repair=model.call.call_args_list[1].args[0]
        self.assertIn('Storyboard heading overflow',repair)
        self.assertIn('Failed draft:',repair)
        self.assertIn('x'*40,repair)

    def test_stale_rewrite_does_not_reuse_wrong_visual_timing(self):
        data=brief();data['script']='A different script.'
        with self.assertRaisesRegex(ValueError,'differ'): validate(data)

    def test_cta_cannot_share_payoff_sentence(self):
        data=brief();data['beats'][3]='Same barcode, new price, so follow Hidden Logic.'
        with self.assertRaisesRegex(ValueError,'separate'): validate(data)

    def test_repeated_query_is_not_three_different_shots(self):
        data=brief();data['broll_keywords']=['Scanner','scanner',' Scanner ']
        with self.assertRaisesRegex(ValueError,'distinct'): validate(data)

    def test_cue_on_unspoken_phrase_is_rejected_before_tts(self):
        data=brief();data['sound_cues'][0]['phrase']='Beep beep'
        with self.assertRaisesRegex(ValueError,'exact'):validate(data)

    def test_decimal_is_not_an_extra_scene(self):
        self.assertEqual(len(sentences('It costs $4.00. Then it costs $3.00.')),2)

    def test_mechanism_plan_cannot_consume_payoff(self):
        data=media_metadata(brief())
        words=[{'word':w,'start':i*.4,'end':i*.4+.3} for i,w in enumerate(data['script'].split())]
        with self.assertRaisesRegex(ValueError,'payoff'):
            plan_scenes(words,data['script'],{},2,3)

    def test_title_is_not_reused_as_caption_layer(self):
        from scriptgen import WRITE_PROMPT,REVIEW_PROMPT
        for prompt in (WRITE_PROMPT,REVIEW_PROMPT):
            self.assertIn('Never draw caption sentences',prompt)
            self.assertIn('broll_keywords (three strings)',prompt)


    def test_opening_word_count_is_only_a_pre_narration_ceiling(self):
        data=brief()
        data['beats'][:2]=["Why's your freezer door tough to reopen?", 'Cold air inside creates a vacuum.']
        self.assertTrue(validate(data))
        data['beats'][0]='Why is the door of your freezer sometimes so difficult to reopen?'
        with self.assertRaisesRegex(ValueError,'drafting ceiling'):validate(data)

if __name__=='__main__':unittest.main()
