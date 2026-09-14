import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from credible.core import UTC, assignment, duplicate, read, save, slots
from credible.evidence import verify_support, FreeModel
from credible.analytics import observation, query_metrics, experiment_report, migrate_legacy, retention_drops
from credible.quality import script_checks
from credible.youtube import deliver
from credible.pipeline import settings
from credible.seeds import RECIPES, build_recipe

class CoreTests(unittest.TestCase):
    def test_singapore_conversion(self):
        rows = slots(settings(), dt.datetime(2026,9,13,0,tzinfo=UTC))
        self.assertEqual([r['publish_at'][11:16] for r in rows], ['07:00','11:00','13:30'])

    def test_missed_slots_roll_forward(self):
        rows = slots(settings(), dt.datetime(2026,9,13,13,tzinfo=UTC))
        self.assertEqual(rows[0]['publish_at'], '2026-09-14T07:00:00+00:00')

    def test_paraphrased_duplicate(self):
        a = {'title': 'Why Red Cars Always Look Faster'}
        b = {'title': 'Why Red Automobiles Look Like Speeding', 'date':'2026-09-12'}
        self.assertTrue(duplicate(a,[b],dt.datetime(2026,9,13,tzinfo=UTC)))

    def test_reserved_claim_never_reselected(self):
        a = {'claim_id':'x','title':'new title'}
        b = {'claim_id':'x','status':'ready','reserved_at':'2025-01-01T00:00:00+00:00'}
        self.assertTrue(duplicate(a,[b]))

    def test_subject_cooldown(self):
        old = {'subject':'dns','title':'old mechanism', 'publish_at':'2026-09-01T00:00:00+00:00'}
        candidate = {'subject':'dns','title':'different mechanism'}
        self.assertTrue(duplicate(candidate,[old],dt.datetime(2026,9,13,tzinfo=UTC)))
        self.assertIsNone(duplicate(candidate,[old],dt.datetime(2026,9,16,tzinfo=UTC)))

    def test_assignment_balances_each_stratum(self):
        history = []
        for _ in range(8):
            history.append({'pillar':'technology','experiment':assignment('technology',0,history)})
        self.assertEqual(sum(x['experiment']['arm']=='question_first' for x in history),4)

    def test_atomic_roundtrip(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'state.json'; save(path,{'a':1})
            self.assertEqual(read(path),{'a':1})
            self.assertFalse(path.with_suffix('.json.tmp').exists())

class EvidenceTests(unittest.TestCase):
    def test_wrong_source_passage_rejected(self):
        e = [{'claim':'x','source_url':'https://example.org','passage':'invented supporting passage','scope':'x'}]
        with self.assertRaises(ValueError):
            verify_support(e,{'https://example.org':{'text':'Something different.'}})

    def test_missing_model_key_is_bounded(self):
        model = FreeModel(settings()); model.key = ''
        with self.assertRaises(RuntimeError): model.call('anything')

    def test_authored_scripts_have_complete_structure(self):
        for recipe in RECIPES:
            source = {'pillar': 'technology', 'url':'https://example.org', 'publisher':'Test publisher'}
            from credible.authored_evidence import PASSAGES
            doc = {'text':' '.join(PASSAGES[recipe[0]]), 'retrieved_at':'2026-09-13T00:00:00+00:00'}
            self.assertTrue(script_checks(build_recipe(recipe,source,doc)),recipe[0])

class AnalyticsTests(unittest.TestCase):
    def test_daily_poll_does_not_invent_first_hour(self):
        r = observation('v',{'viewCount':'900'},dt.datetime(2026,9,13,tzinfo=UTC),'2026-09-12T00:00:00+00:00')
        self.assertEqual(r['age_hours'],24)
        self.assertNotIn('views_first_60m',r)
        self.assertIsNone(r['likes'])

    def test_missing_report_remains_unknown(self):
        api = Mock(); api.reports().query().execute.return_value = {'rows':[]}
        self.assertTrue(all(v is None for v in query_metrics(api,'v','2026-09-01','2026-09-07')['metrics'].values()))

    def test_incomplete_experiment_never_promotes(self):
        self.assertEqual(experiment_report({'videos':{}})['decision'],'continue_balanced_testing')

    def test_legacy_does_not_enter_experiment(self):
        self.assertFalse(migrate_legacy({'v':{'retention':80}})['v']['experiment_eligible'])

    def test_drop_maps_to_scene(self):
        result = retention_drops([[.1,1],[.3,.8]],[{'start':0,'end':5},{'start':5,'end':10}],10)
        self.assertEqual(result[0]['scene'],0)

class UploadTests(unittest.TestCase):
    def test_interrupted_insert_is_not_repeated(self):
        backend = Mock(); backend.find.return_value = None
        row = {'id':'a','status':'uploading','publish_at':'2027-01-01T00:00:00+00:00'}
        with self.assertRaises(RuntimeError): deliver(row,{},Path('.'),backend,lambda:None)
        backend.upload_private.assert_not_called()

    def test_existing_private_upload_recovers(self):
        backend = Mock(); backend.find.return_value = {'id':'existing'}
        row = {'id':'a','status':'uploading','publish_at':'2027-01-01T00:00:00+00:00'}
        deliver(row,{},Path('.'),backend,lambda:None)
        backend.upload_private.assert_not_called()
        self.assertEqual(row['video_id'],'existing')
        self.assertEqual(row['status'],'scheduled')

    def test_quota_error_keeps_uncertain_slot(self):
        backend = Mock(); backend.find.return_value=None; backend.upload_private.side_effect=RuntimeError('quota')
        row = {'id':'a','status':'prepared'}
        with self.assertRaises(RuntimeError): deliver(row,{},Path('.'),backend,lambda:None)
        self.assertEqual(row['status'],'upload_uncertain')

    def test_failed_checkpoint_prevents_upload(self):
        backend = Mock(); backend.find.return_value=None
        def fail(): raise OSError('state push failed')
        with self.assertRaises(OSError): deliver({'id':'a','status':'prepared'}, {},Path('.'),backend,fail)
        backend.upload_private.assert_not_called()

if __name__ == '__main__': unittest.main()
