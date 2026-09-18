import unittest

from research.build_bank import apply_review, subject


class TopicCompilationTests(unittest.TestCase):
    def test_subject_uses_main_object_before_incidental_words(self):
        cases = {
            'Why a fridge warms the kitchen while cooling your milk': 'refrigerators',
            'Why the microwave door has a metal mesh': 'microwave-ovens',
            'Why a spray bottle stops working when tilted too far': 'spray-bottles',
            'Why a robot vacuum can miss a black rug': 'robot-vacuums',
            'Why an air conditioner makes water outside': 'air-conditioners',
            'Why mayonnaise holds oil and water together': 'mayonnaise',
            'Why bakers slash bread before it enters the oven': 'bread',
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(subject(title), expected)

    def test_related_kettle_claims_share_spacing_but_not_claim_identity(self):
        a = apply_review(dict(title='Why your kettle gets quieter before boiling',
                              claim='Steam bubbles collapse in cooler water.'), {})
        b = apply_review(dict(title='Why your kettle knows when to switch itself off',
                              claim='Steam activates the electrical control.'), {})
        self.assertEqual(a['subject'], b['subject'])
        self.assertNotEqual(a['claim_id'], b['claim_id'])

    def test_different_water_fixtures_and_dairy_products_are_not_one_subject(self):
        for titles in [('Why a shower keeps dripping', 'Why a tap aerator has a screen',
                        'Why a toilet refills', 'Why a sink pipe bends'),
                       ('Why milk froths', 'Why cheese stretches', 'Why yoghurt releases liquid')]:
            self.assertEqual(len({subject(t) for t in titles}), len(titles))

    def test_subject_is_object_specific_not_shared_material(self):
        titles = ['Why optical mice struggle on some glass desks',
                  'Why sunglasses make reflections disappear at certain angles',
                  'Why double glazing has a metal strip around the edge',
                  'Why a cold glass gets condensation']
        self.assertEqual(len({subject(t) for t in titles}), len(titles))
        self.assertEqual(subject('Why e-readers flash black'),
                         subject('Why an e-reader keeps an image'))

    def test_reviewed_mechanism_and_subject_replace_discarded_draft(self):
        draft = dict(topic_id='a', claim='Old claim', title='Why a window has a hole')
        original = apply_review(draft,{})
        reviewed = apply_review(draft,dict(claim='Revised mechanism', title='Why e-readers flash black'))
        self.assertNotEqual(original['claim_id'], reviewed['claim_id'])
        self.assertEqual(reviewed['subject'], 'e-readers')

    def test_duplicate_claim_text_does_not_get_new_identity_from_row_number(self):
        a = apply_review(dict(topic_id='a',claim='A shared mechanism.',title='One title'),{})
        b = apply_review(dict(topic_id='b',claim='A shared mechanism!',title='Another title'),{})
        self.assertEqual(a['claim_id'], b['claim_id'])

    def test_curated_canonical_identity_is_preserved(self):
        row = apply_review(dict(claim='Paraphrased explanation',title='Question'),
                           dict(claim_id='canonical-alias',subject='specific-object'))
        self.assertEqual((row['claim_id'],row['subject']),('canonical-alias','specific-object'))
