import copy
import unittest
from unittest.mock import Mock

from credible.topic_review import review_topic, reviewed_bank, review_queue, revision
from test_topics import topic


class TopicReviewTests(unittest.TestCase):
    def case(self):
        lead = topic()
        lead.update(evidence_status='pending_review', support_review=None)
        source = lead['sources'][0]
        docs = {source['url']: {**source, 'text': source['passage']}}
        verdict = dict(supported=True, true_premise=True, non_obvious=True,
            visual_feasible=True, needs_corroboration=False, scope='Specified design',
            reason='Mechanism is directly supported', scores=lead['editorial_scores'],
            evidence=[dict(source_url=source['url'], passage=source['passage'],
                           claim=lead['claim'], scope='Specified design')])
        return lead, docs, verdict

    def test_exact_source_review_can_be_reused_but_changed_claim_cannot(self):
        lead, docs, verdict = self.case()
        saved = review_topic(Mock(call=Mock(return_value=verdict)), lead, docs)
        self.assertEqual(reviewed_bank([lead], {'t1':saved})[0]['evidence_status'], 'reviewed')
        changed = {**lead, 'claim':'A materially different mechanism'}
        self.assertEqual(reviewed_bank([changed], {'t1':saved})[0]['evidence_status'], 'pending_review')

    def test_invented_quote_and_unsupported_claim_fail_closed(self):
        lead, docs, verdict = self.case()
        for change in ('quote', 'claim'):
            bad = copy.deepcopy(verdict)
            if change == 'quote': bad['evidence'][0]['passage'] = 'Invented words not in the source.'
            else: bad['supported'] = False
            with self.assertRaises(ValueError):
                review_topic(Mock(call=Mock(return_value=bad)), lead, docs)

    def test_surprising_claim_requires_independent_publisher(self):
        lead, docs, verdict = self.case()
        verdict['needs_corroboration'] = True
        with self.assertRaisesRegex(ValueError, 'corroboration'):
            review_topic(Mock(call=Mock(return_value=verdict)), lead, docs)

    def test_failed_leads_do_not_starve_untouched_leads_or_retry_same_day(self):
        lead, _, _ = self.case()
        other = {**lead, 'topic_id':'t2'}
        attempts = {'t1':dict(revision=revision(lead), date='2026-09-15')}
        self.assertEqual([t['topic_id'] for t in review_queue([lead,other],attempts,'2026-09-16')], ['t2','t1'])
        self.assertEqual([t['topic_id'] for t in review_queue([lead,other],attempts,'2026-09-15')], ['t2'])

    def test_subdomains_and_labels_cannot_fake_independent_sources(self):
        lead, docs, verdict = self.case()
        base = next(iter(docs.values()))
        for urls in [('https://support.apple.com/a', 'https://developer.apple.com/b'),
                     ('https://qrcode.com/a', 'https://denso-wave.com/b'),
                     ('https://fitbit.com/a', 'https://support.google.com/b')]:
            documents = {u: {**base, 'publisher': str(i)} for i,u in enumerate(urls)}
            verdict['needs_corroboration'] = True
            verdict['evidence'] = [{**verdict['evidence'][0], 'source_url':u} for u in urls]
            with self.assertRaisesRegex(ValueError, 'corroboration'):
                review_topic(Mock(call=Mock(return_value=verdict)), lead, documents)

    def test_redirects_to_one_publisher_do_not_corroborate(self):
        lead, docs, verdict = self.case()
        base = next(iter(docs.values()))
        urls = ['https://one.example/a', 'https://two.example/b']
        documents = {u: {**base, 'resolved_url':'https://support.apple.com/a'} for u in urls}
        verdict['needs_corroboration'] = True
        verdict['evidence'] = [{**verdict['evidence'][0], 'source_url':u} for u in urls]
        with self.assertRaisesRegex(ValueError, 'corroboration'):
            review_topic(Mock(call=Mock(return_value=verdict)), lead, documents)

    def test_two_distinct_publishers_can_support_corroboration(self):
        lead, docs, verdict = self.case()
        base = next(iter(docs.values()))
        urls = ['https://manufacturer.example/a', 'https://university.edu/b']
        documents = {u: base for u in urls}
        verdict['needs_corroboration'] = True
        verdict['evidence'] = [{**verdict['evidence'][0], 'source_url':u} for u in urls]
        self.assertEqual(review_topic(Mock(call=Mock(return_value=verdict)), lead, documents)
                         ['topic']['evidence_status'], 'reviewed')

    def test_new_revision_retries_even_after_same_day_failure(self):
        lead, _, _ = self.case()
        attempts = {'t1':dict(revision=revision(lead), date='2026-09-16')}
        changed = {**lead, 'claim':'Corrected mechanism'}
        self.assertEqual(review_queue([changed], attempts, '2026-09-16'), [changed])

    def test_all_editorial_changes_invalidate_saved_review(self):
        lead, docs, verdict = self.case()
        saved = review_topic(Mock(call=Mock(return_value=verdict)), lead, docs)
        for key,value in {'editorial_note':'Needs a new angle', 'footage':'New close-up',
                          'demonstration':'Revised physical model', 'region':'Canada only',
                          'editorial_scores':{**lead['editorial_scores'],'payoff':0}}.items():
            with self.subTest(key=key):
                changed = {**lead,key:value}
                self.assertEqual(reviewed_bank([changed],{'t1':saved})[0],changed)

    def test_explicit_holds_are_not_automatically_rereviewed(self):
        lead, docs, verdict = self.case()
        for held in ({**lead,'editorial_hold':True},
                     {**lead,'editorial_scores':{**lead['editorial_scores'],'payoff':0}}):
            model=Mock()
            self.assertEqual(review_queue([held],{},'2026-09-17'),[])
            with self.assertRaisesRegex(ValueError, 'editorial hold'):
                review_topic(model,held,docs)
            model.call.assert_not_called()

    def test_authored_review_cannot_be_replaced_by_cached_topic(self):
        authored=topic()
        saved={'revision':revision(authored),'topic':{**authored,'title':'Stale title'}}
        self.assertEqual(reviewed_bank([authored],{'t1':saved}),[authored])
