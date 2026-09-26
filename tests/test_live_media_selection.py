"""Regressions from the September 26 failed preview, without spending API quota."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import editorial_media
import footage_review
import visuals
from credible.topics import eligible, reserve_topic, release_topic
from production_brief import validate
from tests.test_first_draft import brief
from tests.test_topics import topic, AT
from tests.test_service_responses import response


class LiveMediaSelectionTests(unittest.TestCase):
    def test_opening_length_is_measured_rather_than_rejected_by_word_count(self):
        draft = brief()
        draft['beats'][:2] = ['Notice cuts in concrete pavement?',
                              "They're contraction joints, controlling where cracks form."]
        self.assertTrue(validate(draft))
        # A draft passing a word-count heuristic cannot bypass measured timing.
        from credible.quality import timeline_checks
        episode={'production_version':4,'duration':24,'first_answer_end':6.66,
                 'scenes':[{'start':0,'end':24}]}
        with patch('credible.quality.script_checks'):
            with self.assertRaisesRegex(ValueError,'within six seconds'):
                timeline_checks(episode,Path('.'),{'duration_min':20,'duration_max':28})
        draft['beats'][:2] = ['Why cut concrete?', 'To control where cracks form.']
        self.assertTrue(validate(draft))

    def test_repeated_honey_stirring_changes_search_action(self):
        queries = ['honey jar with visible crystals', 'honey being stirred in jar',
                   'honey jar on kitchen counter']
        replacements = [editorial_media._replacement_query(queries, 1, n,
            'Footage failed sampled-frame editorial review: relevant, distinct') for n in range(2)]
        self.assertNotIn(queries[1], replacements)
        self.assertEqual(len(set(replacements)), 2)

    def test_relevance_only_rejection_keeps_the_required_subject(self):
        queries = ['zipper close up', 'zipper on jeans', 'zipper pull tab detail']
        self.assertEqual(editorial_media._replacement_query(queries, 1, 0, 'relevant'), queries[1])

    def test_wide_high_resolution_stock_is_available_but_stays_unverified(self):
        clip = {'id':'test-wide', 'provider':'pixabay', 'url':'https://example.org/clip',
                'video_files':[{'width':1920, 'height':1080, 'link':'https://example.org/media'}]}
        with tempfile.TemporaryDirectory() as directory, patch('visuals.requests.get') as get:
            get.return_value.content = b'wide stock bytes'
            path = str(Path(directory)/'clip.mp4')
            self.assertTrue(visuals._download(clip, path))
            record = json.loads(Path(path+'.source.json').read_text())
            self.assertEqual(record['assessment_status'], 'unverified')
            self.assertEqual(record['source_id'], 'test-wide')
            clip['video_files'][0]['height'] = 720
            self.assertFalse(visuals._download(clip, str(Path(directory)/'too-small.mp4')))

    def test_provider_search_does_not_exclude_all_wide_matches(self):
        with patch('visuals.requests.get') as get, patch.object(visuals, '_RATE_LIMITED', set()):
            get.return_value.status_code = 200
            get.return_value.json.return_value = {'videos':[]}
            visuals._search_pexels('test-key', 'zipper')
            self.assertNotIn('orientation', get.call_args.kwargs['params'])

    def test_reviewer_receives_full_context_and_the_rendered_portrait_crop(self):
        verdict = {'relevant':True, 'exposure_ok':True, 'distinct':True,
                   'description':'A close-up of a zipper pull.'}
        context = {'title':'Why zippers lock', 'script':'A hidden lock. A drawing shows the pin.',
                   'role':'context', 'requested_shot':'zipper close up'}
        with patch('footage_review._ffmpeg', return_value='ffmpeg'), \
             patch('footage_review._unavailable', None), \
             patch('footage_review.subprocess.run', return_value=Mock(stdout=b'frame')) as frames, \
             patch('footage_review.requests.post', return_value=response(verdict)) as post:
            footage_review.assess('clip.mp4', 3, 'A hidden lock.', [], 'test-key', context=context)
        prompt = post.call_args.kwargs['json']['contents'][0]['parts'][0]['text']
        self.assertIn(json.dumps(context), prompt)
        self.assertIn('must actually appear', prompt)
        self.assertIn('near-identical framing/action', prompt)
        filters = [call.args[0][call.args[0].index('-vf')+1] for call in frames.call_args_list]
        self.assertEqual(len(filters), 3)
        self.assertTrue(all('crop=360:640' in value for value in filters))

    def test_context_never_overrides_negative_relevance_or_distinctness(self):
        verdict = {'relevant':True, 'exposure_ok':True, 'distinct':False,
                   'description':'The same honey-stirring composition.'}
        with tempfile.TemporaryDirectory() as directory, \
             patch('footage_review._ffmpeg', return_value='ffmpeg'), \
             patch('footage_review._unavailable', None), \
             patch('footage_review.subprocess.run', return_value=Mock(stdout=b'frame')), \
             patch('footage_review.requests.post', return_value=response(verdict)):
            with self.assertRaisesRegex(footage_review.RejectedFootage, 'distinct'):
                footage_review.assess(str(Path(directory)/'clip.mp4'), 3, 'Glucose crystallizes.',
                    ['Honey stirring'], 'test-key', context={'role':'context'})

    def test_unfilmable_topic_waits_for_other_topics_without_becoming_used(self):
        candidate = topic()
        ledger = {}
        reserve_topic(ledger, candidate, 'preview', AT)
        release_topic(ledger, candidate['topic_id'], 'RejectedFootage', AT)
        self.assertEqual(ledger[candidate['topic_id']]['status'], 'available')
        self.assertFalse(eligible(candidate, [], ledger, AT+dt.timedelta(days=1)))
        self.assertTrue(eligible(candidate, [], ledger, AT+dt.timedelta(days=7)))


if __name__ == '__main__': unittest.main()
