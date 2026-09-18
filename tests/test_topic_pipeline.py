import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from test_first_draft import brief
from test_topics import topic
from credible.evidence import generate_episode, retrieve, source_text_usable
from credible.core import digest, save


class GroundedTopicPipelineTests(unittest.TestCase):
    def test_long_soft_404_shell_is_not_source_text(self):
        self.assertFalse(source_text_usable('Navigation menu ' * 30 + '404 - Page not found'))
        self.assertTrue(source_text_usable('This manual explains the product mechanism. ' * 20))

    def test_pdf_redirected_to_navigation_html_is_rejected(self):
        response = Mock(content=b'<html>' + b'Navigation ' * 50 + b'</html>',
                        headers={'Content-Type':'text/html'}, url='https://manufacturer.example/')
        with tempfile.TemporaryDirectory() as tmp, patch('requests.get',return_value=response):
            with self.assertRaisesRegex(ValueError, 'Expected source PDF'):
                retrieve({'url':'https://manufacturer.example/manual.pdf','publisher':'Maker'},tmp)

    def setup_case(self):
        data=brief(); chosen=topic()
        chosen.update(topic_id='test-barcode',claim_id=data['claim_id'],subject=data['subject'],
                      category='shopping',claim=data['claim'],title=data['title'])
        data.update(topic_id=chosen['topic_id'],category=chosen['category'])
        url=chosen['sources'][0]['url']
        doc={'url':url,'publisher':'Primary test source','text':chosen['sources'][0]['passage'],
             'retrieved_at':chosen['sources'][0]['retrieved_at']}
        verdict={'supported':True,'title_matches':True,'duplicate':False,'visuals_match':True,
                 'natural_script':True,'needs_corroboration':False,'topic_matches':True}
        return data,chosen,doc,verdict

    def test_selected_brief_reaches_writer_and_independent_reviewer(self):
        data,chosen,doc,verdict=self.setup_case()
        model=Mock();model.production_version=4;model.remaining=6;model.call.side_effect=[data,verdict]
        ep=generate_episode(model,{doc['url']:doc},[],'question_first',topic=chosen)
        self.assertEqual(ep['topic_id'],chosen['topic_id'])
        self.assertIn('SELECTED TOPIC BRIEF',model.call.call_args_list[0].args[0])
        self.assertIn('selected_topic',model.call.call_args_list[1].args[0])

    def test_missing_bank_metadata_is_attached_before_semantic_review(self):
        data,chosen,doc,verdict=self.setup_case()
        del data['topic_id']; del data['category']
        model=Mock();model.production_version=4;model.remaining=6;model.call.side_effect=[data,verdict]
        ep=generate_episode(model,{doc['url']:doc},[],'question_first',topic=chosen)
        self.assertEqual(ep['topic_id'],chosen['topic_id'])
        self.assertEqual(ep['category'],chosen['category'])
        self.assertEqual(model.call.call_count,2)

    def test_copied_id_does_not_bypass_semantic_topic_review(self):
        data,chosen,doc,verdict=self.setup_case();verdict['topic_matches']=False
        model=Mock();model.production_version=4;model.remaining=6;model.call.side_effect=[data,verdict]
        with self.assertRaisesRegex(ValueError,'topic drift'):
            generate_episode(model,{doc['url']:doc},[],'question_first',topic=chosen)

    def test_new_categories_preserve_legacy_metadata(self):
        for category, pillar in [('home','technology'),('food','shopping'),('clothing','shopping')]:
            with self.subTest(category=category):
                data,chosen,doc,verdict=self.setup_case()
                chosen['category']=data['category']=category
                model=Mock();model.production_version=4;model.remaining=6;model.call.side_effect=[data,verdict]
                ep=generate_episode(model,{doc['url']:doc},[],'question_first',topic=chosen)
                self.assertEqual((ep['category'],ep['pillar']),(category,pillar))

    def test_wrong_id_is_rejected_before_rendering(self):
        data,chosen,doc,verdict=self.setup_case();data['topic_id']='another-topic'
        model=Mock();model.production_version=4;model.remaining=6;model.call.side_effect=[data,copy.deepcopy(data)]
        with self.assertRaisesRegex(ValueError,'validation'):
            generate_episode(model,{doc['url']:doc},[],'question_first',topic=chosen)

    def test_long_manual_keeps_reviewed_passage_in_writer_context(self):
        data,chosen,doc,verdict=self.setup_case()
        doc['text']=('Irrelevant material. '*5000)+doc['text']+(' Other material. '*5000)
        model=Mock();model.production_version=4;model.remaining=6;model.call.side_effect=[data,verdict]
        generate_episode(model,{doc['url']:doc},[],'question_first',topic=chosen)
        self.assertIn(chosen['sources'][0]['passage'],model.call.call_args_list[0].args[0])

    def test_old_evidence_cache_is_refreshed(self):
        source={'url':'https://example.org/source','publisher':'Test'}
        with tempfile.TemporaryDirectory() as folder:
            save(Path(folder)/(digest(source['url'])[:20]+'.json'),
                 {**source,'retrieved_at':'2020-01-01T00:00:00+00:00','text':'stale'})
            response=Mock();response.content=b'<html>'+b'Current source text. '*30+b'</html>'
            response.text=response.content.decode();response.headers={'Content-Type':'text/html'}
            response.url=source['url'];response.apparent_encoding='utf-8'
            with patch('requests.get',return_value=response) as fetch:
                doc=retrieve(source,folder)
            fetch.assert_called_once();self.assertIn('Current source text.',doc['text'])

    def test_preview_observes_live_reservations_without_double_counting_consumed_reserve(self):
        from credible.pipeline import history
        slot={'id':'slot1','episode_id':'episode1','video_id':'v1','status':'scheduled',
              'claim_id':'m1','publish_at':'2026-09-16T07:00:00+00:00'}
        reserve=[{'id':'episode1','status':'allocated','claim_id':'m1'},
                 {'id':'episode2','status':'ready','claim_id':'m2'}]
        def read_state(path, default=None):
            return {'state/credible/production.json':{'slots':{'slot1':slot}},
                    'state/credible/reserve.json':reserve,
                    'channel_index.json':[{'video_id':'v1','title':'Old title'}]}.get(path,default)
        with patch('credible.pipeline.read',side_effect=read_state):
            rows=history({'slots':{}},[])
        self.assertEqual(len(rows),2)
        self.assertEqual({r['claim_id'] for r in rows},{'m1','m2'})


if __name__=='__main__': unittest.main()
