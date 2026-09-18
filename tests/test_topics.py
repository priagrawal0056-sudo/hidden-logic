import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from credible.core import UTC, assignment, duplicate
from credible.topics import (shortlist, reserve_topic, release_topic, eligible,
                            sync_ledger, verified_documents, validate_bank, load_bank, balanced_slot)
from credible.analytics import experiment_report

AT = dt.datetime(2026, 9, 16, tzinfo=UTC)


def topic(number=1, category='home'):
    return {'topic_id': f't{number}', 'claim_id': f'm{number}', 'subject': f'object{number}',
            'title': f'Observation {number}', 'claim': f'Explanation {number}', 'category': category,
            'observation': 'A concrete detail', 'novelty': 'Unexpected connection', 'scope': 'Specified design',
            'footage': 'Close-up of this detail', 'demonstration': 'Show the internal change',
            'evidence_status': 'reviewed', 'support_review': 'Direct support checked',
            'editorial_scores': dict.fromkeys(('recognition','overlooked_detail','payoff','evidence','visuals'),3),
            'sources': [{'url':'https://example.org/a','publisher':'Manufacturer',
                         'passage':'An exact supporting passage in the document.', 'retrieved_at':AT.isoformat()}]}


class TopicTests(unittest.TestCase):
    def test_slot_balance_rotates_categories_and_balances_openings(self):
        history = []
        for _ in range(21):
            candidates = []
            for category in ('home', 'food', 'clothing'):
                index = balanced_slot(category, (0, 1, 2), history, candidates)
                candidates.append({'category': category,
                    'experiment': assignment(None, index, history + candidates, category)})
            self.assertEqual({r['experiment']['slot_index'] for r in candidates}, {0, 1, 2})
            history.extend(candidates)
        for category in ('home', 'food', 'clothing'):
            for index in (0, 1, 2):
                rows = [r for r in history if r['category'] == category
                        and r['experiment']['slot_index'] == index]
                self.assertLessEqual(abs(len(rows) - 7), 1)
                questions = sum(r['experiment']['arm'] == 'question_first' for r in rows)
                self.assertLessEqual(abs(questions - (len(rows) - questions)), 1)

    def test_slot_balance_only_assigns_unfilled_slots_and_covers_backups(self):
        self.assertEqual(balanced_slot('home', [2]), 2)
        candidates = []
        for category in ('home', 'food', 'clothing', 'shopping', 'transport', 'technology'):
            index = balanced_slot(category, [0, 1, 2], [], candidates)
            candidates.append({'category': category, 'experiment': {'slot_index': index}})
        for index in (0, 1, 2):
            self.assertEqual(sum(r['experiment']['slot_index'] == index for r in candidates), 2)
        with self.assertRaisesRegex(ValueError, 'No open slots'):
            balanced_slot('home', [])

    def test_slot_balance_uses_actual_slot_when_episode_was_reassigned(self):
        history = [{'category': 'home', 'slot_index': 0,
                    'experiment': {'slot_index': 2}}]
        self.assertEqual(balanced_slot('home', [0, 2], history), 2)

    def test_complete_bank_counts_and_required_fields(self):
        self.assertTrue(validate_bank(load_bank()))

    def test_shared_word_is_not_duplicate(self):
        for a,b in [('Why water beads on a waxed car','Why washing machines use less water'),
                    ('Why elevator buttons stay lit','Why shirt buttons are on opposite sides')]:
            self.assertIsNone(duplicate({'title':a},[{'title':b,'date':'2026-09-15'}],AT))

    def test_paraphrased_claim_blocked(self):
        self.assertTrue(duplicate({'title':'Why Red Cars Always Look Faster'},
            [{'title':'Why Red Automobiles Look Like Speeding','date':'2026-09-15'}],AT))

    def test_identical_claim_id_blocks_new_title(self):
        a=topic(); b={**a,'title':'Entirely different words','date':'2026-09-15'}
        self.assertFalse(eligible(a,[b],{},AT))

    def test_new_long_claim_compares_title_with_legacy_title(self):
        candidate={**topic(), 'title':'Why your phone stays on one percent',
                   'claim':'A long technical explanation involving a battery state estimator and display rounding.'}
        self.assertTrue(duplicate(candidate,[{'title':candidate['title'],'date':'2026-09-15'}],AT))

    def test_old_scheduled_history_does_not_extend_claim_cooldown_forever(self):
        a=topic()
        old={**a,'status':'scheduled','publish_at':(AT-dt.timedelta(days=91)).isoformat()}
        self.assertIsNone(duplicate(a,[old],AT))

    def test_different_mechanism_same_subject_needs_cooldown(self):
        a=topic(); b={**topic(2),'subject':a['subject'],'date':'2026-09-15'}
        self.assertFalse(eligible(a,[b],{},AT))
        b['date']='2026-09-01'; self.assertTrue(eligible(a,[b],{},AT))

    def test_claim_cooldown_boundary(self):
        a=topic(); b={**a,'publish_at':(AT-dt.timedelta(days=90)).isoformat()}
        self.assertTrue(eligible(a,[b],{},AT))
        b['publish_at']=(AT-dt.timedelta(days=89)).isoformat()
        self.assertFalse(eligible(a,[b],{},AT))

    def test_old_ready_reserve_stays_blocked(self):
        a=topic(); b={**a,'date':'2020-01-01','status':'ready'}
        self.assertFalse(eligible(a,[b],{},AT))

    def test_unrendered_reservation_blocks_related_subject_then_expires(self):
        a,b=topic(),topic(2)
        b['subject']=a['subject']
        ledger={};reserve_topic(ledger,a,'run',AT)
        self.assertFalse(eligible(b,[],ledger,AT))
        self.assertTrue(eligible(b,[],ledger,AT+dt.timedelta(hours=7)))

    def test_bank_source_failures_remain_unknown(self):
        a=topic(); a['evidence_status']='pending_research'
        self.assertEqual(shortlist([a],at=AT),[])
        a=topic(); a['editorial_scores']['evidence']=0
        self.assertEqual(shortlist([a],at=AT),[])

    def test_first_six_have_distinct_categories_when_available(self):
        rows=[topic(i,c) for i,c in enumerate(('home','food','clothing','technology','shopping','transport'))]
        rows += [topic(10,'home')]
        chosen=shortlist(rows,at=AT)
        self.assertEqual(len({r['category'] for r in chosen}),6)

    def test_recent_category_overrepresentation_penalized(self):
        rows=[topic(1,'home'),topic(2,'food')]
        self.assertEqual(shortlist(rows,[{'category':'home','date':'2026-09-15'}],n=1,at=AT)[0]['category'],'food')

    def test_shortlist_does_not_mutate_bank_or_ledger(self):
        rows=[topic()]; original=copy.deepcopy(rows); ledger={}
        shortlist(rows,ledger=ledger,at=AT)
        self.assertEqual(rows,original); self.assertEqual(ledger,{})

    def test_reservation_expires_but_upload_uncertain_does_not(self):
        a=topic(); ledger={}; reserve_topic(ledger,a,'slot',AT)
        self.assertFalse(eligible(a,[],ledger,AT))
        later=AT+dt.timedelta(hours=7)
        self.assertTrue(eligible(a,[],ledger,later))
        ledger['t1']['status']='upload_uncertain'
        self.assertFalse(eligible(a,[],ledger,later))
        release_topic(ledger,'t1','quota',later)
        self.assertEqual(ledger['t1']['status'],'upload_uncertain')

    def test_failed_generation_can_retry_without_being_used(self):
        a=topic(); ledger={}; reserve_topic(ledger,a,'slot',AT)
        release_topic(ledger,'t1','quota',AT)
        self.assertFalse(eligible(a,[],ledger,AT))
        self.assertTrue(eligible(a,[],ledger,AT+dt.timedelta(hours=7)))

    def test_prepared_episode_survives_retry(self):
        a=topic(); ledger={}; reserve_topic(ledger,a,'slot',AT)
        sync_ledger(ledger,[{**a,'id':'episode','status':'prepared'}])
        release_topic(ledger,'t1','process interrupted',AT)
        self.assertFalse(eligible(a,[],ledger,AT+dt.timedelta(days=1)))

    def test_missing_or_changed_passage_rejected(self):
        with self.assertRaises(ValueError): verified_documents(topic(),{})
        with self.assertRaises(ValueError):
            verified_documents(topic(),{'https://example.org/a':{'text':'Unrelated page'}})

    def test_category_assignment_excludes_old_experiment(self):
        old=[{'category':'home','experiment':{'id':'early-answer-v1','arm':'demonstration_first','slot_index':0}}]
        self.assertEqual(assignment(None,0,old,'home')['arm'],'demonstration_first')
        new=[]
        for _ in range(6): new.append({'category':'home','experiment':assignment(None,0,new,'home')})
        self.assertEqual(sum(r['experiment']['arm']=='question_first' for r in new),3)

    def test_old_and_new_analytics_are_not_pooled(self):
        metrics={'engagedViews':500,'averageViewDuration':20,'averageViewPercentage':80,
                 'shares':5,'subscribersGained':3,'subscribersLost':0}
        row={'experiment_eligible':True,'experiment':{'id':'early-answer-v1','arm':'question_first'},
             'seven_day':{'metrics':metrics}}
        report=experiment_report({'videos':{'v':row}},'everyday-topics-v2')
        self.assertEqual(report['arms']['question_first']['eligible_videos'],0)
        self.assertFalse(report['automatic_promotion'])

    def test_legacy_picker_uses_new_bank_without_writes(self):
        import idea_bank
        with patch.object(idea_bank,'load_bank',return_value=[topic()]), patch.object(idea_bank,'history',return_value=([],{})):
            self.assertEqual(idea_bank.pick_unused(1,log=lambda _:None),['Observation 1'])


if __name__=='__main__': unittest.main()
