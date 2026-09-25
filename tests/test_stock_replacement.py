import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import editorial_media
import footage_review
import visuals


class StockReplacementTests(unittest.TestCase):
    @staticmethod
    def _asset(folder, name, content=None):
        path = Path(folder) / (name + '.mp4')
        path.write_bytes((content or name).encode())
        Path(str(path) + '.source.json').write_text(json.dumps({
            'source_id': name, 'license': 'test-license', 'provider': 'test',
            'sha256': editorial_media.file_hash(path), 'assessment_status': 'unverified'}))
        return str(path)

    @staticmethod
    def _pass(name):
        return {'assessment_status': 'sampled_frames_checked',
                'assessment': {'description': name, 'relevant': True,
                               'exposure_ok': True, 'distinct': True}}

    def _run(self, folder, fetches, reviews):
        words = [{'word': word, 'start': i, 'end': i + .5}
                 for i, word in enumerate(['Hook.', 'Answer.', 'Explain.', 'Payoff.', 'Follow.'])]
        (Path(folder) / 'timings.json').write_text(json.dumps(words))
        scenes = [{'start': i, 'end': i + 1, 'kind': kind,
                   'sentence_start': i, 'sentence_count': 1}
                  for i, kind in enumerate(['stock', 'stock', 'diagram', 'stock', 'callback'])]
        with patch.object(editorial_media, 'plan_scenes', return_value=scenes), \
                patch.object(editorial_media.assemble, 'sentence_segments', return_value=[1] * 5), \
                patch.object(visuals, 'fetch_backgrounds', side_effect=fetches) as fetch, \
                patch.object(footage_review, 'assess', side_effect=reviews) as assess, \
                patch.object(editorial_media, 'render_diagram', side_effect=RuntimeError('stop before encoding')):
            with self.assertRaises((ValueError, RuntimeError)) as error:
                editorial_media.render({'script': 'Hook. Answer. Explain. Payoff. Follow.',
                    'broll_keywords': ['first query', 'second query', 'third query']}, folder,
                    {'pexels_api_key': 'stock', 'gemini_api_key': 'test'})
        checkpoint = json.loads((Path(folder) / 'stock-checkpoint.json').read_text())
        return fetch, assess, error.exception, checkpoint

    def test_rejected_clip_is_replaced_then_every_remaining_scene_is_reviewed(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = [self._asset(folder, name) for name in ('a', 'bad', 'c')]
            better = self._asset(folder, 'better')
            fetch, assess, error, checkpoint = self._run(folder, [initial, [better]],
                [self._pass('a'), footage_review.RejectedFootage('Wrong subject'),
                 self._pass('better'), self._pass('c')])
            self.assertEqual(str(error), 'stop before encoding')
            self.assertEqual(assess.call_count, 4)
            self.assertEqual(assess.call_args_list[-1].args[3], ['a', 'better'])
            self.assertEqual(fetch.call_args_list[-1].args[1], ['second query'])
            self.assertEqual(fetch.call_args.kwargs['excluded_source_ids'], {'a', 'bad', 'c'})
            self.assertEqual(checkpoint['replacement_attempts'], [0, 1, 0])
            self.assertEqual(checkpoint['assets'][1]['source_id'], 'better')
            self.assertEqual(checkpoint['rejected_assets'][0]['source_id'], 'bad')
            self.assertEqual(json.loads((Path(folder) / 'used_clips.json').read_text()), ['a', 'better', 'c'])

    def test_quota_during_replacement_review_preserves_selection_and_accepted_prefix(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = [self._asset(folder, name) for name in ('a', 'bad', 'c')]
            better = self._asset(folder, 'better')
            _, _, error, checkpoint = self._run(folder, [initial, [better]],
                [self._pass('a'), footage_review.RejectedFootage('Wrong subject'), RuntimeError('quota')])
            self.assertEqual(str(error), 'quota')
            self.assertEqual(checkpoint['assets'][1]['source_id'], 'better')
            self.assertEqual(checkpoint['replacement_attempts'], [0, 1, 0])
            self.assertEqual(len(checkpoint['reviews']), 1)
            fetch, assess, error, checkpoint = self._run(folder, [], [self._pass('better'), self._pass('c')])
            fetch.assert_not_called()
            self.assertEqual(assess.call_count, 2)
            self.assertEqual(assess.call_args_list[0].args[0], better)
            self.assertEqual(assess.call_args_list[0].args[3], ['a'])
            self.assertEqual(checkpoint['replacement_attempts'], [0, 1, 0])
            self.assertEqual(str(error), 'stop before encoding')

    def test_repeated_bad_choices_are_bounded_and_not_reassessed_on_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = [self._asset(folder, name) for name in ('bad', 'b', 'c')]
            alternatives = [self._asset(folder, name) for name in ('bad2', 'bad3')]
            _, assess, error, checkpoint = self._run(folder, [initial, [alternatives[0]], [alternatives[1]]],
                [footage_review.RejectedFootage('Wrong subject')] * 3)
            self.assertEqual(assess.call_count, 3)
            self.assertIn('after two replacements', str(error))
            self.assertEqual(checkpoint['replacement_attempts'], [2, 0, 0])
            fetch, assess, error, _ = self._run(folder, [], [])
            fetch.assert_not_called()
            assess.assert_not_called()
            self.assertIn('after two replacements', str(error))
            self.assertFalse((Path(folder) / 'used_clips.json').exists())

    def test_temporary_replacement_search_failures_do_not_exhaust_alternatives(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = [self._asset(folder, name) for name in ('bad', 'b', 'c')]
            better = self._asset(folder, 'better')
            _, _, error, checkpoint = self._run(folder,
                [initial, RuntimeError('Temporary stock outage')],
                [footage_review.RejectedFootage('Wrong subject')])
            self.assertEqual(str(error), 'Temporary stock outage')
            self.assertEqual(checkpoint['replacement_attempts'], [0, 0, 0])
            _, assess, error, checkpoint = self._run(folder,
                [RuntimeError('Temporary stock outage')], [])
            assess.assert_not_called()
            self.assertEqual(checkpoint['replacement_attempts'], [0, 0, 0])
            fetch, assess, error, checkpoint = self._run(folder, [[better]],
                [self._pass('better'), self._pass('b'), self._pass('c')])
            self.assertEqual(str(error), 'stop before encoding')
            self.assertEqual(checkpoint['replacement_attempts'], [1, 0, 0])
            self.assertEqual(assess.call_count, 3)
            self.assertEqual(fetch.call_args.kwargs['filename_prefix'], 'replacement_1_1')

    def test_service_and_schema_failures_do_not_reject_or_replace_the_clip(self):
        for failure in (RuntimeError('service unavailable'), ValueError('incomplete response')):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                initial = [self._asset(folder, name) for name in ('a', 'b', 'c')]
                fetch, assess, error, checkpoint = self._run(folder, [initial], [failure])
                self.assertIs(error, failure)
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(assess.call_count, 1)
                self.assertEqual(checkpoint['replacement_attempts'], [0, 0, 0])
                self.assertEqual(checkpoint['rejected_assets'], [])

    def test_changed_earlier_shot_invalidates_later_cached_reviews(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = [self._asset(folder, name) for name in ('a', 'bad', 'c')]
            _, _, _, checkpoint = self._run(folder, [initial], [self._pass('a'), RuntimeError('quota')])
            checkpoint['reviews'] += [{'assessment_status': 'incomplete'}, self._pass('stale-c')]
            (Path(folder) / 'stock-checkpoint.json').write_text(json.dumps(checkpoint))
            better = self._asset(folder, 'better')
            _, assess, _, checkpoint = self._run(folder, [[better]],
                [footage_review.RejectedFootage('Wrong subject'), self._pass('better'), self._pass('new-c')])
            self.assertEqual(assess.call_count, 3)
            self.assertEqual(assess.call_args_list[-1].args[3], ['a', 'better'])
            self.assertEqual(checkpoint['reviews'][-1]['assessment']['description'], 'new-c')

    def test_replacement_cannot_repeat_any_existing_source(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = [self._asset(folder, name) for name in ('a', 'bad', 'c')]
            _, assess, error, checkpoint = self._run(folder, [initial, [initial[0]]],
                [self._pass('a'), footage_review.RejectedFootage('Wrong subject')])
            self.assertIn('repeats an existing or rejected source', str(error))
            self.assertEqual(assess.call_count, 2)
            self.assertEqual(checkpoint['assets'][1]['source_id'], 'bad')

    def test_downloader_excludes_rejected_identity_and_same_bytes_under_other_identity(self):
        import hashlib
        candidates = [{'id': name} for name in ('rejected', 'same-bytes', 'fresh')]
        downloaded = []
        def download(candidate, path):
            downloaded.append(candidate['id'])
            Path(path).write_bytes(b'rejected content' if candidate['id'] == 'same-bytes' else b'fresh content')
            return True
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(visuals, '_search_all', return_value=candidates), \
                patch.object(visuals, '_detect_concept', return_value=None), \
                patch.object(visuals, '_download', side_effect=download), \
                patch.object(visuals, '_load_used', return_value=set()), \
                patch.object(visuals, '_save_used') as history, \
                patch.object(visuals.time, 'sleep'):
            paths = visuals.fetch_backgrounds('stock', ['specific object'], folder, count=1,
                metadata_scoring=False, excluded_source_ids={'rejected'},
                excluded_sha256={hashlib.sha256(b'rejected content').hexdigest()},
                filename_prefix='replacement_2_1', record_history=False)
            self.assertEqual(downloaded, ['same-bytes', 'fresh'])
            self.assertEqual(Path(paths[0]).name, 'replacement_2_1_1.mp4')
            self.assertEqual(Path(paths[0]).read_bytes(), b'fresh content')
            history.assert_not_called()


if __name__ == '__main__':
    unittest.main()
