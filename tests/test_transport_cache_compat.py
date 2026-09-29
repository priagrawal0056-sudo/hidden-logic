import hashlib
import tempfile
import unittest
from pathlib import Path

import editorial_media
from credible.cache_compat import asset_code_hash
from credible.core import digest, file_hash, read

ROOT = Path(__file__).resolve().parents[1]


class TransportCacheCompatibilityTests(unittest.TestCase):
    def test_only_exact_reviewed_transport_update_keeps_old_asset_contract(self):
        records = read(ROOT/'credible/transport_cache_compat.json')
        for name, record in records.items():
            normalized = (ROOT/name).read_bytes().replace(b'\r\n', b'\n')
            self.assertEqual(hashlib.sha256(normalized).hexdigest(), record['transport_update_sha256'])
            for crlf in (False, True):
                with self.subTest(file=name, crlf=crlf), tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp)/name
                    path.write_bytes(normalized.replace(b'\n', b'\r\n') if crlf else normalized)
                    old = record['previous_crlf_sha256' if crlf else 'previous_lf_sha256']
                    self.assertEqual(asset_code_hash(path), old)
                    path.write_bytes(path.read_bytes()+b'\n# Different future implementation\n')
                    self.assertEqual(asset_code_hash(path), file_hash(path))
                    self.assertNotEqual(asset_code_hash(path), old)

    def test_saved_narration_contract_stays_compatible_without_ignoring_other_style(self):
        records = read(ROOT/'credible/transport_cache_compat.json')
        style = dict(editorial_media.fingerprint())
        self.assertIn(style['tts.py'], (records['tts.py']['previous_lf_sha256'],
                                       records['tts.py']['previous_crlf_sha256']))
        self.assertEqual(style['captions.py'], file_hash(ROOT/'captions.py'))
        self.assertEqual(style['assemble.py'], file_hash(ROOT/'assemble.py'))

    def test_stock_signature_preserves_prior_review_contract_and_query_sensitivity(self):
        meta = {'script': 'Same complete narration.', 'broll_keywords': ['barcode scanner'], 'title': 'Barcode'}
        words, scenes = [], []
        legacy = read(ROOT/'credible/transport_cache_compat.json')['footage_review.py']
        old_hash = legacy['previous_crlf_sha256' if b'\r\n' in (ROOT/'footage_review.py').read_bytes() else 'previous_lf_sha256']
        old_signature = digest({'version': 1, 'script': meta['script'], 'words': words,
            'queries': meta['broll_keywords'], 'scenes': scenes, 'title': meta['title'],
            'visual_thesis': meta['script'], 'first_frame_description': '',
            'stock_selection_code': file_hash(ROOT/'visuals.py'), 'frame_review_code': old_hash})
        self.assertEqual(editorial_media._stock_signature(meta, words, scenes), old_signature)
        self.assertNotEqual(editorial_media._stock_signature({**meta, 'broll_keywords': ['car']}, words, scenes), old_signature)
