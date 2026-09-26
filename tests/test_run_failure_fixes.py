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

    def test_axis_aligned_arrows_keep_safe_endpoint_checks(self):
        from credible.authored_boards import board
        from credible.storyboard import validate_storyboard
        for box in ([100,300,100,0],[200,300,-100,0],[100,300,0,100]):
            plan=board('barcode')
            plan[0]['objects'].append({'type':'arrow','box':box,'color':'accent'})
            self.assertTrue(validate_storyboard(plan))
        for box in ([100,300,-100,0],[100,300,0,0],[100,300,0,-200]):
            plan=board('barcode')
            plan[0]['objects'].append({'type':'arrow','box':box,'color':'accent'})
            with self.assertRaises(ValueError):validate_storyboard(plan)

    def test_quota_failure_stops_other_gemini_consumers_in_same_run(self):
        import tempfile
        from pathlib import Path
        import service_limits
        import footage_review
        from credible.evidence import FreeModel
        response=Mock(status_code=429)
        with tempfile.TemporaryDirectory() as directory, service_limits.session(), patch('requests.post',return_value=response) as post:
            with self.assertRaises(service_limits.ServiceUnavailable):
                tts._try_gemini_tts('Hello.',str(Path(directory)/'unused.mp3'),str(Path(directory)/'unused.json'),'key')
            model=FreeModel({'model':'gemini-2.5-flash','max_model_calls':5})
            with self.assertRaises(service_limits.ServiceUnavailable):model.call('draft')
            with self.assertRaises(service_limits.ServiceUnavailable):
                footage_review.assess('unused.mp4',2,'Hello.',[],'key')
            self.assertEqual(post.call_count,1)
        self.assertFalse(service_limits.blocked())
        with service_limits.session():self.assertFalse(service_limits.blocked())

    def test_reserve_failures_have_a_per_run_attempt_limit(self):
        import service_limits
        from credible.pipeline import seed_reserve, RECIPES
        from pathlib import Path
        catalog=[{'id':r[0],'url':'https://example.org/'+r[0]} for r in RECIPES]
        docs={s['url']:{} for s in catalog};errors=[]
        with service_limits.session(), patch('credible.pipeline.build_recipe',return_value={'id':'test'}), \
             patch('credible.pipeline.history',return_value=[]), patch('credible.pipeline.duplicate',return_value=None), \
             patch('credible.pipeline.verify_support'), patch('credible.pipeline.prepare',side_effect=RuntimeError('unavailable')) as prepare:
            # Evidence validation receives a real key even in this isolated fixture.
            with patch('credible.pipeline.build_recipe',return_value={'id':'test','evidence':[]}):
                seed_reserve(Path('.'),{'production_version':4,'reserve_build_attempts_per_run':2},docs,catalog,{},[],errors,9)
            self.assertEqual(prepare.call_count,2)
            self.assertEqual(len(errors),2)

    def test_all_consumers_share_request_spacing(self):
        import service_limits
        with service_limits.session(), patch('service_limits.time.monotonic',side_effect=[0,2,15]), patch('service_limits.time.sleep') as sleep:
            service_limits.before_request()
            service_limits.before_request()
            sleep.assert_called_once_with(13)

    def test_service_failure_report_keeps_safe_status(self):
        import service_limits
        import tempfile
        import json
        from pathlib import Path
        from credible.single import main
        for status in (401, 403, 429):
            with tempfile.TemporaryDirectory() as directory:
                with patch('sys.argv', ['single', '--output', directory]), patch(
                        'credible.single.build', side_effect=service_limits.ServiceUnavailable(status)):
                    if status == 429:
                        main()
                    else:
                        with self.assertRaises(SystemExit):
                            main()
                report = json.loads((Path(directory) / 'result.json').read_text())
                self.assertIn(f'HTTP {status}', report['reason'])
                self.assertEqual(report['status'], 'deferred_quota' if status == 429 else 'failed')
                self.assertFalse(report['published'])

    def test_writer_schema_is_sent_but_review_requests_stay_independent(self):
        from credible.evidence import FreeModel
        from credible.draft_schema import DRAFT_SCHEMA
        response=Mock(status_code=200,ok=True)
        response.json.return_value={'candidates':[{'content':{'parts':[{'text':'{}'}]}}]}
        model=FreeModel({'model':'gemini-2.5-flash','max_model_calls':2});model.key='test'
        with patch('requests.post',return_value=response) as post:
            model.call('draft',schema=DRAFT_SCHEMA)
            self.assertEqual(post.call_args.kwargs['json']['generationConfig']['responseJsonSchema'],DRAFT_SCHEMA)
            model.call('review')
            self.assertNotIn('responseJsonSchema',post.call_args.kwargs['json']['generationConfig'])

    def test_invalid_request_diagnostics_redact_secrets_and_urls(self):
        from credible.evidence import FreeModel
        model=FreeModel({'model':'gemini-2.5-flash','max_model_calls':1});model.key='private-key'
        response=Mock(status_code=400,ok=False)
        response.json.return_value={'error':{'message':'Unknown schema field; private-key https://example.com/?key=private-key'}}
        with patch('requests.post',return_value=response):
            with self.assertRaises(RuntimeError) as caught:model.call('draft')
        self.assertIn('unknown schema field',str(caught.exception))
        self.assertNotIn('private-key',str(caught.exception))
        self.assertNotIn('https://',str(caught.exception))

    def test_ambiguous_optional_effects_do_not_abort_valid_narration(self):
        from production_brief import usable_sound_cues
        beats=['Pressure?', 'It changes.', 'Air lowers pressure.', 'Pressure matters. Follow Hidden Logic.']
        good={'phrase':'Air lowers pressure','kind':'chime'}
        cues,notes=usable_sound_cues(beats,[{'phrase':'pressure','kind':'chime'},good,good,{'phrase':'Follow Hidden Logic','kind':'bad'}])
        self.assertEqual(cues,[good])
        self.assertEqual(len(notes),3)
        self.assertEqual(usable_sound_cues(beats,[None])[0],[])
