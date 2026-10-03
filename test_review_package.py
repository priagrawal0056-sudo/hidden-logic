import json
import tempfile
import unittest
from pathlib import Path

import review_package


class ReviewPackageTests(unittest.TestCase):
    def test_review_page_shows_video_story_and_sanitized_source_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "unpublished"
            workdir = root / "technology-01"
            (workdir / "frame_review").mkdir(parents=True)
            (workdir / "short.mp4").write_bytes(b"video")
            (workdir / "frame_review" / "beat_1.jpg").write_bytes(b"frame")
            meta = {
                "title": '<img src=x onerror="alert(1)">',
                "topic": "A small observed action",
                "script": "<script>alert('spoken text')</script>",
                "voice_identity": "Orus",
                "voice_direction": "curious_observation",
                "tts_model": "gemini-test-tts",
                "human_review_status": "pending",
                "footage_shots": [{
                    "beat": "observation",
                    "provider": "Pexels",
                    "creator": "Example creator",
                    "license": "Pexels license",
                    "source_url": "https://www.pexels.com/video/example/?api_key=must-not-leak#fragment",
                    "source_start": 1.25,
                    "crop_position": {"x": "center", "y": "top"},
                    "sampled_frames": [{"path": "frame_review/beat_1.jpg", "time_seconds": 2.5}],
                    "review": {
                        "status": "accepted",
                        "visible_action": "<b>Hand lifts the small object</b>",
                    },
                }],
            }
            (workdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            page = review_package.write_review_page(
                root,
                [{
                    "pilot_id": "technology-01",
                    "status": "ready_for_human_review",
                    "human_review_status": "pending",
                    "workdir": str(workdir),
                }],
                title="Pilot review",
            )

            rendered = page.read_text(encoding="utf-8")
            self.assertIn('src="technology-01/short.mp4"', rendered)
            self.assertIn("Read the narration", rendered)
            self.assertIn("Footage, action, crop, and source records", rendered)
            self.assertIn("frame_review/beat_1.jpg", rendered)
            self.assertIn("Human review:</strong> pending", rendered)
            self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;", rendered)
            self.assertIn("&lt;script&gt;alert(&#x27;spoken text&#x27;)&lt;/script&gt;", rendered)
            self.assertIn("&lt;b&gt;Hand lifts the small object&lt;/b&gt;", rendered)
            self.assertIn("https://www.pexels.com/video/example/\"", rendered)
            self.assertNotIn("must-not-leak", rendered)
            self.assertNotIn("<script>alert", rendered)
            self.assertNotIn("<button", rendered.lower())
            self.assertNotIn("/api/approve", rendered.lower())
            self.assertIn("does not record an approval or publish", rendered)

    def test_skipped_slot_is_explained_and_out_of_package_paths_are_not_linked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "review"
            outside = Path(temp) / "outside"
            outside.mkdir()
            (outside / "short.mp4").write_bytes(b"not in review package")
            page = review_package.write_review_page(
                root,
                [{
                    "pilot_id": "queues-travel-01",
                    "status": "skipped",
                    "skip_reason": "No relevant action-visible footage passed review.",
                    "workdir": str(outside),
                    "meta": {"topic": "A queue at a station"},
                }],
            )

            rendered = page.read_text(encoding="utf-8")
            self.assertIn("No rendered MP4 in this slot.", rendered)
            self.assertIn("No relevant action-visible footage passed review.", rendered)
            self.assertNotIn('src="../outside/short.mp4"', rendered)


if __name__ == "__main__":
    unittest.main()
