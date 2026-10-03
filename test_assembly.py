"""Offline tests for reviewed crop/timing behavior and interrupted FFmpeg renders."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import assemble


class CropAndSegmentTests(unittest.TestCase):
    def test_reviewed_crop_position_maps_to_vertical_crop(self):
        self.assertEqual(assemble._crop_fractions({"x": "left", "y": "top"}), (0.0, 0.0))
        self.assertEqual(assemble._crop_fractions({"x": "right", "y": "bottom"}), (1.0, 1.0))
        self.assertEqual(assemble._crop_fractions({"x": "center", "y": "center"}), (0.5, 0.5))
        with self.assertRaises(ValueError):
            assemble._crop_fractions({"x": "outside", "y": "center"})

    def test_strict_segments_preserve_five_beat_durations(self):
        durations = [2.5, 3.0, 4.0, 2.0, 3.5]
        got = assemble._normalized_segments(sum(durations), durations, 5, True)
        self.assertEqual(got, durations)
        with self.assertRaisesRegex(ValueError, "requires five shots"):
            assemble._normalized_segments(10, [2, 2], 2, True)
        with self.assertRaisesRegex(ValueError, "differ from audio"):
            assemble._normalized_segments(20, durations, 5, True)

    def test_filter_graph_uses_reviewed_source_start_and_crop(self):
        graph = assemble.build_video_filter_graph(
            ["shot.mp4"], [3.25],
            [{"source_start": 4.5, "crop_position": {"x": "left", "y": "bottom"}}],
            "captions.ass",
        )
        self.assertIn("trim=start=4.500:duration=3.250", graph)
        self.assertIn("x='(in_w-1188)*0.000'", graph)
        self.assertIn("y='(in_h-2112)*1.000'", graph)
        self.assertNotIn("zoompan", graph)
        self.assertNotIn("loop", graph)
        self.assertNotIn("fade", graph)

    def test_invalid_reviewed_crop_is_rejected_before_render(self):
        with self.assertRaisesRegex(ValueError, "invalid reviewed crop"):
            assemble.build_video_filter_graph(
                ["shot.mp4"], [3.0],
                [{"source_start": 0, "crop_position": {"x": "middle-ish", "y": "center"}}],
                "captions.ass",
            )


class InterruptedRenderTests(unittest.TestCase):
    def test_interrupted_ffmpeg_render_fails_without_creating_success_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clips = []
            records = []
            for index in range(5):
                clip = root / f"bg_{index}.mp4"
                clip.write_bytes(b"clip")
                clips.append(str(clip))
                records.append({
                    "clip_id": f"clip-{index}",
                    "sha256": f"hash-{index}",
                    "local_path": str(clip),
                    "source_start": 0.2,
                    "crop_position": {"x": "center", "y": "center"},
                })
            voice = root / "voice.mp3"
            voice.write_bytes(b"voice")
            ass = root / "captions.ass"
            ass.write_text("[Events]\n", encoding="utf-8")
            timings = root / "timings.json"
            timings.write_text("[]", encoding="utf-8")
            out = root / "short.mp4"

            with mock.patch.object(assemble, "_audio_duration", return_value=15.0), \
                    mock.patch.object(assemble, "_probe_duration", return_value=20.0), \
                    mock.patch.object(assemble.subprocess, "run", return_value=SimpleNamespace(
                        returncode=1, stderr="simulated interrupted render"
                    )) as ffmpeg:
                with self.assertRaisesRegex(RuntimeError, "ffmpeg failed"):
                    assemble.assemble(
                        clips, str(voice), str(timings), str(ass), str(out),
                        seg_seconds=[3.0] * 5, shot_records=records, strict_editorial=True,
                    )
            self.assertEqual(ffmpeg.call_count, 1)
            self.assertFalse(out.exists())

    def test_strict_render_rejects_duplicate_stock_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clips, records = [], []
            for index in range(5):
                clip = root / f"bg_{index}.mp4"
                clip.write_bytes(b"clip")
                clips.append(str(clip))
                records.append({
                    "clip_id": "reused" if index < 2 else f"clip-{index}",
                    "sha256": f"hash-{index}", "local_path": str(clip),
                    "source_start": 0, "crop_position": {"x": "center", "y": "center"},
                })
            with mock.patch.object(assemble, "_audio_duration", return_value=15.0):
                with self.assertRaisesRegex(ValueError, "duplicate clip IDs/hashes"):
                    assemble.assemble(
                        clips, "voice.mp3", "timings.json", "captions.ass", "out.mp4",
                        seg_seconds=[3.0] * 5, shot_records=records, strict_editorial=True,
                    )


if __name__ == "__main__":
    unittest.main()
