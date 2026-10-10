"""Offline regression tests for the Orus/Gemini TTS path. No API calls are made."""
import json
import os
import tempfile
import unittest
from unittest import mock

import tts


SCRIPT = (
    "A phone charger bends beside the plug. A thin wire can break inside the insulation. "
    "The outer sleeve may still look fine. The phone then charges only when the cable rests "
    "just so. Replacing the cable is safer than pulling it by the cord."
)
ANSWER = "A thin wire can break inside the insulation."


def _word_timings(text: str) -> list[dict]:
    result = []
    for index, word in enumerate(text.split()):
        start = 0.15 + index * 0.29
        result.append({"word": word, "start": round(start, 3), "end": round(start + 0.22, 3)})
    return result


def _metrics(text: str) -> dict:
    return {
        "transcript": text,
        "transcript_accuracy": 1.0,
        "duration_seconds": 24.0,
        "max_pause_seconds": 0.7,
        "word_duration_cv": 0.22,
        "pitch_span_semitones": 3.6,
        "clipping_detected": False,
        "timing_source": "faster-whisper-word-timestamps",
    }


class GeminiRequestTests(unittest.TestCase):
    def test_direction_is_structured_and_never_spoken(self):
        body = tts._gemini_tts_request_body(
            SCRIPT, "Orus", "curious_observation", "gemini-3.8-flash-tts"
        )
        content = body["input"][0]["content"][0]
        self.assertEqual(content, {"type": "text", "text": SCRIPT})
        self.assertEqual(body["generation_config"]["speech_config"][0]["voice"], "Orus")
        self.assertEqual(body["model"], "gemini-3.8-flash-tts")
        self.assertEqual(body["response_format"]["mime_type"], "audio/wav")
        # No style/delivery text of any kind may reach Gemini.
        serialized = json.dumps(body).lower()
        self.assertNotIn("annotations", serialized)
        self.assertNotIn("speech_metadata", serialized)
        self.assertNotIn("curious", serialized)
        self.assertNotIn("style", serialized)

    def test_voice_transcript_and_direction_are_locked(self):
        with self.assertRaises(RuntimeError):
            tts._gemini_tts_request_body(SCRIPT, "OtherVoice", "curious_observation", "model")
        with self.assertRaises(ValueError):
            tts._gemini_tts_request_body(SCRIPT, "Orus", "unknown", "model")
        with self.assertRaises(ValueError):
            tts._gemini_tts_request_body("  ", "Orus", "curious_observation", "model")

    def test_internal_tts_prompt_is_rejected_instead_of_spoken(self):
        with self.assertRaisesRegex(ValueError, "internal TTS/production instruction"):
            tts._gemini_tts_request_body(
                "Read this in a warm, curious tone. " + SCRIPT,
                "Orus", "curious_observation", "gemini-3.8-flash-tts",
            )

    def test_interactions_audio_payload_is_extracted(self):
        import base64
        expected = b"RIFF" + b"sample-audio"
        got, mime = tts._extract_interaction_audio({
            "output_audio": {"data": base64.b64encode(expected).decode(), "mime_type": "audio/wav"}
        })
        self.assertEqual(got, expected)
        self.assertEqual(mime, "audio/wav")


class SynthesisTakeTests(unittest.TestCase):
    def _synthesize(self, issues_by_take):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        audio_path = os.path.join(temp.name, "voice.mp3")
        timings_path = os.path.join(temp.name, "timings.json")
        metadata = {"first_answer_quote": ANSWER}
        directions = []

        def fake_write(text, path, key, voice, direction, model):
            directions.append(direction)
            with open(path, "wb") as fh:
                fh.write(b"mock audio payload")

        responses = iter(issues_by_take)

        def fake_metrics(text, path):
            return _word_timings(text), _metrics(text), next(responses)

        return temp, audio_path, timings_path, metadata, directions, fake_write, fake_metrics

    def test_primary_take_is_saved_with_verified_metadata(self):
        temp, audio, timings, metadata, directions, writer, metric_reader = self._synthesize([[]])
        with mock.patch.object(tts, "_write_gemini_audio", side_effect=writer) as mocked_write, \
                mock.patch.object(tts, "_take_metrics", side_effect=metric_reader):
            words = tts.synthesize(
                SCRIPT, audio, timings, api_key="offline-test-key", metadata=metadata,
                direction="curious_observation",
            )
        self.assertEqual(mocked_write.call_count, 1)
        self.assertEqual(directions, ["curious_observation"])
        self.assertTrue(os.path.isfile(audio))
        with open(timings, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), words)
        self.assertEqual(metadata["voice_identity"], "Orus")
        self.assertEqual(metadata["tts_take"], 1)
        self.assertEqual(metadata["tts_engine"], "gemini")
        self.assertEqual(metadata["tts_style_prompt"], "none")
        self.assertIs(metadata["tts_style_prompt_sent"], False)
        self.assertTrue(metadata["transcript_verified"])
        self.assertEqual(metadata["timing_source"], "faster-whisper-word-timestamps")
        self.assertLessEqual(metadata["tts_quality"]["first_answer_seconds"], 6.0)

    def test_one_alternate_take_only_after_quality_failure(self):
        temp, audio, timings, metadata, directions, writer, metric_reader = self._synthesize([
            ["overly_even_word_timing"], [],
        ])
        with mock.patch.object(tts, "_write_gemini_audio", side_effect=writer) as mocked_write, \
                mock.patch.object(tts, "_take_metrics", side_effect=metric_reader):
            tts.synthesize(
                SCRIPT, audio, timings, api_key="offline-test-key", metadata=metadata,
                direction="curious_observation",
            )
        self.assertEqual(mocked_write.call_count, 2)
        # Retries keep the same editorial label; only the audio is regenerated.
        self.assertEqual(directions, ["curious_observation", "curious_observation"])
        self.assertEqual(metadata["tts_take"], 2)
        self.assertEqual(metadata["voice_direction"], "curious_observation")
        self.assertEqual(metadata["tts_style_prompt"], "none")
        self.assertIs(metadata["tts_style_prompt_sent"], False)

    def test_both_bad_takes_fail_without_saving_audio_or_timing_fallback(self):
        temp, audio, timings, metadata, directions, writer, metric_reader = self._synthesize([
            ["transcript_mismatch"], ["flat_pitch_movement"],
        ])
        with mock.patch.object(tts, "_write_gemini_audio", side_effect=writer) as mocked_write, \
                mock.patch.object(tts, "_take_metrics", side_effect=metric_reader):
            with self.assertRaises(tts.TTSQualityError):
                tts.synthesize(
                    SCRIPT, audio, timings, api_key="offline-test-key", metadata=metadata,
                    direction="curious_observation",
                )
        self.assertEqual(mocked_write.call_count, 2)
        self.assertFalse(os.path.exists(audio))
        self.assertFalse(os.path.exists(timings))

    def test_narration_prompt_leak_is_rejected_before_any_tts_call(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with mock.patch.object(tts, "_write_gemini_audio") as writer:
            with self.assertRaisesRegex(tts.TTSQualityError, "internal TTS/production instruction"):
                tts.synthesize(
                    "Read this in a warm, curious tone. " + SCRIPT,
                    os.path.join(temp.name, "voice.mp3"),
                    os.path.join(temp.name, "timings.json"),
                    api_key="offline-test-key", direction="curious_observation",
                )
        writer.assert_not_called()

    def test_prompt_direction_spoken_by_tts_fails_audio_transcript_review(self):
        transcript = "Read this in a warm, curious tone. " + SCRIPT
        words = _word_timings(transcript)
        with mock.patch.object(tts, "_transcribe_audio", return_value=(transcript, words)), \
                mock.patch.object(tts, "_audio_duration", return_value=25.0), \
                mock.patch.object(tts, "_pitch_span_and_peak", return_value=(3.6, False)):
            _words, _metrics, issues = tts._take_metrics(SCRIPT, "offline-fake.mp3")
        self.assertIn("tts_direction_spoken_in_audio", issues)

    def test_api_failure_does_not_trigger_a_second_take_or_voice_fallback(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with mock.patch.object(tts, "_write_gemini_audio", side_effect=OSError("offline")) as writer:
            with self.assertRaisesRegex(RuntimeError, "refusing alternate-engine fallback"):
                tts.synthesize(
                    SCRIPT, os.path.join(temp.name, "voice.mp3"),
                    os.path.join(temp.name, "timings.json"), api_key="offline-test-key",
                )
        writer.assert_called_once()

    def test_missing_api_key_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "Gemini API key is required"):
            tts.synthesize(SCRIPT, "voice.mp3", "timings.json", api_key="")


if __name__ == "__main__":
    unittest.main()
