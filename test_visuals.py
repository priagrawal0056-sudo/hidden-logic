"""Offline tests for footage review gates, uniqueness, and evidence metadata."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    import requests  # noqa: F401
except ImportError:
    # Network calls are mocked below; keep unit discovery independent of installed extras.
    requests_stub = types.ModuleType("requests")
    requests_stub.get = lambda *args, **kwargs: None
    requests_stub.post = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_stub

import visuals


QUERIES = [
    "shopper lifting cereal box from supermarket shelf",
    "hand reading unit price on cereal shelf label",
    "close-up of package size printed on cereal box",
    "compare two cereal boxes beside shelf prices",
    "shopper choosing cereal after comparing price",
]
SENTENCES = [f"A visible action happens during story beat number {index}." for index in range(5)]


def _review(action="shopper checks the shelf label", **overrides):
    result = {
        "relevant": True,
        "category_match": True,
        "action_visible": True,
        "score": 8.7,
        "visible_action": action,
        "reason": "The requested subject and action are visible in the sampled frames.",
        "recommended_window": 0,
        "crop_x": "center",
        "crop_y": "center",
    }
    result.update(overrides)
    return result


class VisualReviewTests(unittest.TestCase):
    def test_frame_review_requires_relevance_category_action_and_valid_crop(self):
        self.assertEqual(visuals._valid_visual_review(_review(), 1), (True, ""))
        rejected = [
            (_review(relevant=False), "off_topic_stock_clip"),
            (_review(category_match=False), "stock_category_mismatch"),
            (_review(action_visible=False), "missing_visible_action"),
            (_review(crop_x="diagonal"), "invalid_reviewed_crop_x"),
            (_review(score=4.0), "visual_relevance_below_threshold"),
            (_review(recommended_window=2), "invalid_reviewed_source_window"),
        ]
        for payload, reason in rejected:
            with self.subTest(reason=reason):
                valid, got = visuals._valid_visual_review(payload, 1)
                self.assertFalse(valid)
                self.assertEqual(got, reason)

    def test_five_shot_contract_fails_before_network_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(visuals.FootageGateError, "five positive narration-aligned"):
                visuals.fetch_backgrounds(
                    "pexels-test", QUERIES, tmp, count=5, gemini_api_key="gemini-test",
                    segment_durations=[2.0], sentences=SENTENCES,
                )

    def test_corrupt_used_clip_registry_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "used_clips.json"
            registry.write_text("not-json", encoding="utf-8")
            with mock.patch.object(visuals, "CACHE_FILE", str(registry)):
                with self.assertRaisesRegex(RuntimeError, "refusing to risk footage reuse"):
                    visuals._load_used()

    def test_missing_sampled_frame_reviewer_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(visuals.FootageGateError, "Gemini key is required"):
                visuals.fetch_backgrounds(
                    "pexels-test", QUERIES, tmp, count=5, gemini_api_key=None,
                    segment_durations=[2.0] * 5, sentences=SENTENCES,
                )

    def _candidate(self, index):
        return {
            "provider": "pexels",
            "id": f"px-{index}",
            "provider_id": str(index),
            "source_url": f"https://www.pexels.com/video/{index}/",
            "creator": f"creator-{index}",
            "creator_url": f"https://www.pexels.com/@creator-{index}",
            "license": "Pexels License",
            "duration_seconds": 20.0,
            "video_files": [],
        }

    def _fake_download(self, video, path):
        Path(path).write_bytes((video["id"] + " unique footage bytes").encode())
        video["selected_file"] = {"url": "https://cdn.example/video.mp4", "width": 1080, "height": 1920}
        return True

    def _fake_samples(self, path, duration, segment_duration, review_dir, beat_index):
        Path(review_dir).mkdir(parents=True, exist_ok=True)
        frames = []
        for index in range(2):
            frame = Path(review_dir) / f"frame-{index}.jpg"
            frame.write_bytes(b"x" * 1500)
            frames.append(str(frame))
        return ([{"window_index": 0, "source_start": 0.0,
                  "sample_times": [0.5, 1.5], "frame_paths": frames}], [0.0])

    def test_fetch_returns_five_unique_reviewed_clips_with_crop_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = {}
            candidates = {query: [self._candidate(i)] for i, query in enumerate(QUERIES)}
            actions = iter([f"distinct visible action {i}" for i in range(5)])
            with mock.patch.object(visuals, "_search_all", side_effect=lambda keys, q: candidates[q]), \
                    mock.patch.object(visuals, "_download", side_effect=self._fake_download), \
                    mock.patch.object(visuals, "_probe_duration", return_value=20.0), \
                    mock.patch.object(visuals, "_sample_clip_windows", side_effect=self._fake_samples), \
                    mock.patch.object(visuals, "_review_sampled_frames", side_effect=lambda *args: (
                        _review(next(actions)), "gemini-test-model"
                    )), \
                    mock.patch.object(visuals, "_load_used", return_value=set()), \
                    mock.patch.object(visuals, "_save_used"):
                paths = visuals.fetch_backgrounds(
                    "pexels-test", QUERIES, tmp, count=5, gemini_api_key="gemini-test",
                    segment_durations=[2.0] * 5, sentences=SENTENCES,
                    topic="cereal unit prices", episode_meta=metadata,
                )
            self.assertEqual(len(paths), 5)
            self.assertEqual(len(set(paths)), 5)
            shots = metadata["footage_shots"]
            self.assertEqual(len({shot["clip_id"] for shot in shots}), 5)
            self.assertEqual(len({shot["sha256"] for shot in shots}), 5)
            self.assertEqual(shots[0]["source_start"], 0.0)
            self.assertEqual(shots[0]["crop_position"], {"x": "center", "y": "center"})
            self.assertEqual(shots[0]["license"], "Pexels License")
            self.assertTrue(shots[0]["review"]["action_visible"])
            self.assertEqual(metadata["visual_review_status"],
                             "automated frame review passed; human review pending")

    def test_reused_clip_id_cannot_fill_second_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._candidate(0)
            search_count = 0

            def search(_keys, _query):
                nonlocal search_count
                search_count += 1
                return [dict(candidate)]

            with mock.patch.object(visuals, "_search_all", side_effect=search), \
                    mock.patch.object(visuals, "_download", side_effect=self._fake_download), \
                    mock.patch.object(visuals, "_probe_duration", return_value=20.0), \
                    mock.patch.object(visuals, "_sample_clip_windows", side_effect=self._fake_samples), \
                    mock.patch.object(visuals, "_review_sampled_frames", return_value=(
                        _review(), "gemini-test-model"
                    )), \
                    mock.patch.object(visuals, "_load_used", return_value=set()), \
                    mock.patch.object(visuals, "_save_used"):
                with self.assertRaisesRegex(visuals.FootageGateError, "beat 2.*clip_id_reused"):
                    visuals.fetch_backgrounds(
                        "pexels-test", QUERIES, tmp, count=5, gemini_api_key="gemini-test",
                        segment_durations=[2.0] * 5, sentences=SENTENCES, topic="cereal prices",
                    )
            self.assertGreaterEqual(search_count, 2)


if __name__ == "__main__":
    unittest.main()
