import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import editorial_media
import visuals


class StockRequestBudgetTests(unittest.TestCase):
    def test_deferred_metadata_scoring_leaves_all_downloads_unverified(self):
        candidates = [{'id': 'clip-' + str(i)} for i in range(3)]
        downloaded = []

        def download(candidate, path):
            downloaded.append(dict(candidate))
            Path(path).write_bytes(candidate['id'].encode())
            return True

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(visuals, '_search_all', side_effect=[[v] for v in candidates]), \
                patch.object(visuals, '_score_candidates') as score, \
                patch.object(visuals, '_download', side_effect=download), \
                patch.object(visuals, '_load_used', return_value=set()), \
                patch.object(visuals, '_save_used'), \
                patch.object(visuals.time, 'sleep'):
            paths = visuals.fetch_backgrounds('stock', ['freezer', 'door', 'handle'], folder,
                count=3, gemini_api_key='test', metadata_scoring=False)
        self.assertEqual(len(paths), 3)
        score.assert_not_called()
        self.assertTrue(all(v['assessment_status'] == 'unverified' for v in downloaded))
        self.assertTrue(all(v['score'] == 0 for v in downloaded))

    def test_legacy_fetch_keeps_metadata_scoring_by_default(self):
        def download(candidate, path):
            Path(path).write_bytes(b'distinct clip')
            return True

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(visuals, '_search_all', return_value=[{'id': 'clip'}]), \
                patch.object(visuals, '_score_candidates', return_value={'clip': 9}) as score, \
                patch.object(visuals, '_download', side_effect=download), \
                patch.object(visuals, '_load_used', return_value=set()), \
                patch.object(visuals, '_save_used'), \
                patch.object(visuals.time, 'sleep'):
            visuals.fetch_backgrounds('stock', ['freezer'], folder, count=1, gemini_api_key='test')
        score.assert_called_once()

    def _render_stock(self, folder, assessment, expect_fetch=True):
        folder = Path(folder)
        words = [{'word': word, 'start': i, 'end': i + .5}
                 for i, word in enumerate(['Hook.', 'Answer.', 'Explain.', 'Payoff.', 'Follow.'])]
        (folder / 'timings.json').write_text(json.dumps(words))
        paths = []
        for i in range(3):
            path = folder / f'clip-{i}.mp4'
            path.write_bytes(str(i).encode())
            Path(str(path) + '.source.json').write_text(json.dumps({
                'source_id': f'stock-{i}', 'license': 'test-license',
                'provider': 'test', 'sha256': editorial_media.file_hash(path),
                'assessment_status': 'unverified'}))
            paths.append(str(path))
        scenes = [{'start': i, 'end': i + 1, 'kind': kind,
                   'sentence_start': i, 'sentence_count': 1}
                  for i, kind in enumerate(['stock', 'stock', 'diagram', 'stock', 'callback'])]
        with patch.object(editorial_media, 'plan_scenes', return_value=scenes), \
                patch.object(editorial_media.assemble, 'sentence_segments', return_value=[1] * 5), \
                patch.object(visuals, 'fetch_backgrounds', return_value=paths) as fetch, \
                patch('footage_review.assess', side_effect=assessment) as review, \
                patch.object(editorial_media, 'render_diagram', side_effect=RuntimeError('stop before encoding')), \
                patch.object(editorial_media.assemble, 'assemble') as encode:
            with self.assertRaises((ValueError, RuntimeError)) as error:
                editorial_media.render({'script': 'Hook. Answer. Explain. Payoff. Follow.',
                    'broll_keywords': ['freezer', 'door', 'handle']}, folder,
                    {'pexels_api_key': 'stock', 'gemini_api_key': 'test'})
        if expect_fetch:
            self.assertIs(fetch.call_args.kwargs['metadata_scoring'], False)
        else:
            fetch.assert_not_called()
        encode.assert_not_called()
        return review, error

    def test_approved_path_still_reviews_every_clip_and_passes_prior_descriptions(self):
        def assessment(path, duration, spoken, previous, key):
            return {'assessment_status': 'sampled_frames_checked',
                    'assessment': {'description': Path(path).stem,
                                   'relevant': True, 'exposure_ok': True, 'distinct': True}}

        with tempfile.TemporaryDirectory() as folder:
            review, error = self._render_stock(folder, assessment)
        self.assertEqual(str(error.exception), 'stop before encoding')
        self.assertEqual(review.call_count, 3)
        self.assertEqual(review.call_args_list[0].args[3], [])
        self.assertEqual(review.call_args_list[2].args[3], ['clip-0', 'clip-1'])

    def test_failed_sampled_frame_review_still_blocks_render(self):
        with tempfile.TemporaryDirectory() as folder:
            review, error = self._render_stock(folder, ValueError('Footage failed sampled-frame editorial review'))
        self.assertIn('failed sampled-frame', str(error.exception))
        self.assertEqual(review.call_count, 1)

    @staticmethod
    def _passing_review(description):
        return {'assessment_status': 'sampled_frames_checked',
                'assessment': {'description': description, 'relevant': True,
                               'exposure_ok': True, 'distinct': True}}

    def test_quota_on_second_review_resumes_without_redownloading_or_rechecking_first(self):
        with tempfile.TemporaryDirectory() as folder:
            review, error = self._render_stock(folder, [self._passing_review('clip-0'),
                                                        RuntimeError('Gemini HTTP 429')])
            self.assertEqual(review.call_count, 2)
            self.assertIn('429', str(error.exception))
            checkpoint = json.loads((Path(folder) / 'stock-checkpoint.json').read_text())
            self.assertEqual(len(checkpoint['assets']), 3)
            self.assertEqual(len(checkpoint['reviews']), 1)
            review, error = self._render_stock(folder,
                [self._passing_review('clip-1'), self._passing_review('clip-2')], expect_fetch=False)
            self.assertEqual(str(error.exception), 'stop before encoding')
            self.assertEqual(review.call_count, 2)
            self.assertEqual(review.call_args_list[0].args[3], ['clip-0'])
            self.assertEqual(review.call_args_list[1].args[3], ['clip-0', 'clip-1'])
            checkpoint = json.loads((Path(folder) / 'stock-checkpoint.json').read_text())
            self.assertEqual(len(checkpoint['reviews']), 3)

    def test_unreviewed_downloads_survive_quota_on_first_assessment(self):
        with tempfile.TemporaryDirectory() as folder:
            self._render_stock(folder, RuntimeError('Gemini HTTP 429'))
            checkpoint = json.loads((Path(folder) / 'stock-checkpoint.json').read_text())
            self.assertEqual(len(checkpoint['assets']), 3)
            self.assertEqual(checkpoint['reviews'], [])
            review, _ = self._render_stock(folder,
                [self._passing_review(f'clip-{i}') for i in range(3)], expect_fetch=False)
            self.assertEqual(review.call_count, 3)

    def test_missing_or_modified_download_and_provenance_invalidate_cache(self):
        for mutation in ('missing', 'bytes', 'provenance', 'signature', 'outside'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                self._render_stock(folder, RuntimeError('quota'))
                root = Path(folder)
                checkpoint = json.loads((root / 'stock-checkpoint.json').read_text())
                signature = checkpoint['signature']
                if mutation == 'missing':
                    (root / 'clip-0.mp4').unlink()
                elif mutation == 'bytes':
                    (root / 'clip-0.mp4').write_bytes(b'changed')
                elif mutation == 'provenance':
                    path = root / 'clip-0.mp4.source.json'
                    record = json.loads(path.read_text())
                    record['source_id'] = 'different-source'
                    path.write_text(json.dumps(record))
                elif mutation == 'signature':
                    signature = 'new-episode-signature'
                else:
                    checkpoint['assets'][0]['path'] = '../clip-0.mp4'
                    (root / 'stock-checkpoint.json').write_text(json.dumps(checkpoint))
                self.assertIsNone(editorial_media._load_stock_checkpoint(root, signature, 3))

    def test_incomplete_cached_review_and_later_reviews_are_never_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            self._render_stock(folder, RuntimeError('quota'))
            path = Path(folder) / 'stock-checkpoint.json'
            checkpoint = json.loads(path.read_text())
            checkpoint['reviews'] = [self._passing_review('clip-0'),
                {'assessment_status': 'sampled_frames_checked', 'assessment': {'description': 'incomplete'}},
                self._passing_review('clip-2')]
            path.write_text(json.dumps(checkpoint))
            loaded, _ = editorial_media._load_stock_checkpoint(Path(folder), checkpoint['signature'], 3)
            self.assertEqual(len(loaded['reviews']), 1)
            review, _ = self._render_stock(folder,
                [self._passing_review('clip-1'), self._passing_review('clip-2')], expect_fetch=False)
            self.assertEqual(review.call_count, 2)

    def test_incomplete_new_assessment_does_not_create_passing_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            _, error = self._render_stock(folder, [{'assessment_status': 'sampled_frames_checked',
                                                  'assessment': {'description': 'missing verdicts'}}])
            self.assertIn('incomplete', str(error.exception))
            checkpoint = json.loads((Path(folder) / 'stock-checkpoint.json').read_text())
            self.assertEqual(checkpoint['reviews'], [])

    def test_signature_binds_script_queries_timings_and_current_review_code(self):
        meta = {'script': 'One.', 'broll_keywords': ['one', 'two', 'three']}
        words = [{'word': 'One.', 'start': 0, 'end': 1}]
        scenes = [{'start': 0, 'end': 2, 'kind': 'stock'}]
        baseline = editorial_media._stock_signature(meta, words, scenes)
        self.assertNotEqual(baseline, editorial_media._stock_signature({**meta, 'script': 'Two.'}, words, scenes))
        self.assertNotEqual(baseline, editorial_media._stock_signature({**meta, 'broll_keywords': ['changed']}, words, scenes))
        self.assertNotEqual(baseline, editorial_media._stock_signature(meta, [{**words[0], 'end': 1.1}], scenes))
        self.assertNotEqual(baseline, editorial_media._stock_signature(meta, words, [{**scenes[0], 'end': 2.1}]))
        with patch.object(editorial_media, 'file_hash', return_value='changed-code'):
            self.assertNotEqual(baseline, editorial_media._stock_signature(meta, words, scenes))


if __name__ == '__main__':
    unittest.main()
