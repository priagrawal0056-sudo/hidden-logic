"""Fail-closed publication and reserve tests; no remote upload is performed."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import publication
import captions
import editorial_quality as eq


_VALID_SCRIPT = (
    "A shopper lifts a cereal box beside the shelf tag. "
    "The unit price shows what each box costs for the same amount. "
    "A larger sale label can hide that the package holds less cereal. "
    "Comparing the unit prices makes the better-value size easier to spot. "
    "Check the shelf label before choosing which box to put in your cart."
)
_VALID_TITLE = "Cereal Unit Prices Make the Shelf Check Clear"
_VALID_TOPIC = "cereal unit price labels"
_VALID_QUERIES = [
    "shopper lifting cereal box beside supermarket shelf tag",
    "hand reading unit price on cereal shelf label",
    "close-up of cereal package size printed beside nutrition panel",
    "compare two different cereal boxes next to price labels",
    "shopper choosing cereal after checking unit price",
]
_VALID_ANSWER = "The unit price shows what each box costs for the same amount."
_VALID_EVIDENCE = {
    "mechanism": "Unit pricing expresses package cost using a common quantity.",
    "supported_claims": ["A unit price can be used to compare differently sized packages."],
    "sources": [{"title": "Unit pricing guidance", "url": "https://example.org/unit-pricing"}],
}


def _valid_review_metadata(root: Path) -> dict:
    words = []
    cursor = 0.15
    sentences = eq.split_sentences(_VALID_SCRIPT)
    for sentence in sentences:
        for word in sentence.split():
            words.append({"word": word, "start": round(cursor, 3), "end": round(cursor + 0.23, 3)})
            cursor += 0.31
        cursor += 0.55
    timing_path = root / "timings.json"
    timing_path.write_text(__import__("json").dumps(words), encoding="utf-8")
    captions.build_ass(str(timing_path), str(root / "captions.ass"), ["unit price"])
    (root / "short.mp4").write_bytes(b"x" * 12_000)
    durations = eq.five_beat_segment_durations(_VALID_SCRIPT, words, words[-1]["end"] + 0.8)
    beats = []
    shots = []
    for index, (sentence, duration, query) in enumerate(zip(sentences, durations, _VALID_QUERIES)):
        clip = root / f"bg_{index+1}.mp4"
        clip.write_bytes(f"unique reviewed clip {index}".encode())
        import hashlib
        frames = []
        for frame_index in range(2):
            frame = root / "frame_review" / f"beat_{index+1}" / f"frame_{frame_index}.jpg"
            frame.parent.mkdir(parents=True, exist_ok=True)
            frame.write_bytes(b"frame" * 400)
            frames.append({"path": str(frame.relative_to(root)), "time_seconds": 0.5 + frame_index})
        beats.append({
            "beat": ("observation", "action_start", "detail", "change_comparison", "payoff")[index],
            "sentence": sentence,
            "duration_seconds": round(duration, 3),
        })
        shots.append({
            "beat": beats[-1]["beat"], "query": query,
            "provider": "pexels", "provider_id": str(index + 1),
            "clip_id": f"px_{index+1}", "source_url": f"https://pexels.com/video/{index+1}/",
            "download_url": "https://cdn.example/clip.mp4", "license": "Pexels License",
            "creator": f"creator-{index+1}", "creator_url": f"https://pexels.com/@creator-{index+1}",
            "duration_seconds": 20.0, "segment_duration_seconds": round(duration, 3),
            "source_start": 0.0, "crop_position": {"x": "center", "y": "center"},
            "sha256": hashlib.sha256(clip.read_bytes()).hexdigest(), "local_path": str(clip),
            "sampled_frames": frames,
            "review": {
                "status": "accepted", "score": 8.5, "relevant": True,
                "category_match": True, "action_visible": True,
                "visible_action": f"unique visible action {index+1}",
                "reviewed_source_start": 0.0,
            },
        })
    answer_at = eq.first_answer_time(_VALID_SCRIPT, words, _VALID_ANSWER)
    return {
        "script": _VALID_SCRIPT, "title": _VALID_TITLE, "topic": _VALID_TOPIC,
        "broll_keywords": _VALID_QUERIES, "first_answer_quote": _VALID_ANSWER,
        "evidence_record": _VALID_EVIDENCE, "title_score": 25,
        "title_frustration": 8, "voice": "Orus", "voice_identity": "Orus",
        "voice_direction": "curious_observation", "tts_engine": "gemini",
        "tts_model": "gemini-3.8-flash-tts", "tts_take": 1,
        "timing_source": "faster-whisper-word-timestamps", "transcript_verified": True,
        "transcript_actual": _VALID_SCRIPT,
        "tts_quality": {
            "transcript_accuracy": 1.0, "duration_seconds": 24.0,
            "max_pause_seconds": 0.7, "word_duration_cv": 0.22,
            "pitch_span_semitones": 3.5, "clipping_detected": False,
            "first_answer_seconds": answer_at,
        },
        "story_beats": beats, "footage_shots": shots,
        "caption_quality": {"timing_source": "verified_word_boundaries", "fade": False},
        "render_expected_duration_seconds": round(words[-1]["end"] + 0.8, 3),
        "render_quality": {
            "video_codec": "h264", "audio_codec": "aac", "width": 1080,
            "height": 1920, "duration_seconds": round(words[-1]["end"] + 0.8, 3),
            "mean_volume_db": -14.0, "peak_volume_db": -1.5,
        },
    }


class PublicationGateTests(unittest.TestCase):
    def test_rollout_defaults_to_blocked(self):
        with self.assertRaisesRegex(publication.PublicationBlocked, "rollout_enabled must remain false"):
            publication.assert_publication_allowed({}, source="test upload")
        with self.assertRaises(publication.PublicationBlocked):
            publication.assert_publication_allowed({"rollout_enabled": False})

    def test_rollout_flag_alone_is_not_enough_without_six_pilot_review(self):
        with self.assertRaisesRegex(publication.PublicationBlocked, "pilot_review_complete"):
            publication.assert_publication_allowed({"rollout_enabled": True})

    def test_pilot_requires_explicit_human_approval(self):
        cfg = {"rollout_enabled": True, "pilot_review_complete": True}
        pending = {"pilot_mode": True, "pilot_id": "technology-01",
                   "human_review_status": "pending"}
        with self.assertRaisesRegex(publication.PublicationBlocked, "not human-approved"):
            publication.assert_publication_allowed(cfg, pending)

    def test_config_loader_defaults_missing_rollout_flags_to_false(self):
        import config_loader
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {}, clear=True):
            path = Path(tmp) / "empty.json"
            path.write_text("{}", encoding="utf-8")
            cfg = config_loader.load_config(str(path))
        self.assertIs(cfg["rollout_enabled"], False)
        self.assertIs(cfg["pilot_review_complete"], False)

    def test_actions_rollout_variables_are_explicit_boolean_overrides(self):
        import config_loader
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            "os.environ", {
                "HL_ROLLOUT_ENABLED": "true",
                "HL_PILOT_REVIEW_COMPLETE": "no",
            }, clear=True,
        ):
            path = Path(tmp) / "config.json"
            path.write_text("{}", encoding="utf-8")
            cfg = config_loader.load_config(str(path))
        self.assertIs(cfg["rollout_enabled"], True)
        self.assertIs(cfg["pilot_review_complete"], False)

    def test_pilot_rejection_and_missing_quality_meta_are_blocked(self):
        with self.assertRaises(publication.PublicationBlocked) as caught:
            publication.assert_publication_allowed(
                {"rollout_enabled": True, "pilot_review_complete": True},
                {"human_review_status": "rejected"}
            )
        self.assertIn("user_rejected_episode", str(caught.exception))
        with self.assertRaises(publication.PublicationBlocked) as caught:
            publication.assert_publication_allowed(
                {"rollout_enabled": True, "pilot_review_complete": True}, {}
            )
        self.assertIn("verified_word_timings_missing", str(caught.exception))

    def test_upload_path_checks_rollout_before_requesting_youtube_service(self):
        try:
            import upload
        except ImportError as exc:
            self.skipTest(f"YouTube client dependency is not installed: {exc}")
        with mock.patch("config_loader.load_config", return_value={"rollout_enabled": False}), \
                mock.patch.object(upload, "_service") as service:
            with self.assertRaises(publication.PublicationBlocked):
                upload.upload("not-created.mp4", "title", "description", [])
            service.assert_not_called()

    def test_upload_only_gate_blocks_before_upload_api(self):
        import upload
        import upload_only
        with mock.patch.object(upload, "upload") as upload_api:
            with self.assertRaises(publication.PublicationBlocked):
                upload_only.upload_single_draft(
                    "not-created.mp4", ".", {}, None, False,
                    {"rollout_enabled": False, "pilot_review_complete": False},
                )
            upload_api.assert_not_called()

    def test_complete_editorial_package_can_pass_machine_gates(self):
        from types import SimpleNamespace
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            metadata = _valid_review_metadata(root)
            with mock.patch.object(eq, "validate_render", return_value=([], metadata["render_quality"])), \
                    mock.patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="20.0")):
                self.assertEqual(eq.validate_episode_meta(metadata, root), [])
                publication.assert_publication_allowed(
                    {"rollout_enabled": True, "pilot_review_complete": True}, metadata, root
                )

    def test_invalid_render_geometry_fails_reserve(self):
        with tempfile.TemporaryDirectory() as tmp:
            metadata = _valid_review_metadata(Path(tmp))
            metadata["render_quality"]["width"] = 720
            issues = eq.validate_episode_meta(metadata)
            self.assertIn("render_quality_metadata_invalid", issues)

    def test_interrupted_upload_never_returns_a_success_url_or_marker(self):
        try:
            import upload
        except ImportError as exc:
            self.skipTest(f"YouTube client dependency is not installed: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "short.mp4"
            video.write_bytes(b"rendered file")
            marker = Path(tmp) / "uploaded.txt"
            with mock.patch("config_loader.load_config", return_value={"rollout_enabled": True, "pilot_review_complete": True}), \
                    mock.patch.object(upload, "_service", side_effect=RuntimeError("simulated network interruption")):
                with self.assertRaisesRegex(RuntimeError, "simulated network interruption"):
                    upload.upload(str(video), "title", "description", [])
            self.assertFalse(marker.exists())

    def test_config_example_keeps_rollout_explicitly_disabled(self):
        import json
        example = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        self.assertIs(example.get("rollout_enabled"), False)
        self.assertIs(example.get("pilot_review_complete"), False)


if __name__ == "__main__":
    unittest.main()
