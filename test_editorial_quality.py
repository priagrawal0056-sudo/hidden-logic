"""Deterministic offline tests for script, timing, caption, and reserve gates."""
import json
import tempfile
import unittest
from pathlib import Path

import captions
import editorial_quality as eq


SCRIPT = (
    "A shopper lifts a cereal box beside the shelf tag. "
    "The unit price shows what each box costs for the same amount. "
    "A larger sale label can hide that the package holds less cereal. "
    "Comparing the unit prices makes the better-value size easier to spot. "
    "Check the shelf label before choosing which box to put in your cart."
)
TITLE = "Cereal Unit Prices Make the Shelf Check Clear"
TOPIC = "cereal unit price labels"
QUERIES = [
    "shopper lifting cereal box beside supermarket shelf tag",
    "hand reading unit price on cereal shelf label",
    "close-up of cereal package size printed beside nutrition panel",
    "compare two different cereal boxes next to price labels",
    "shopper choosing cereal after checking unit price",
]
EVIDENCE = {
    "mechanism": "Unit pricing expresses package cost using a common quantity.",
    "supported_claims": ["A unit price can be used to compare differently sized packages."],
    "sources": [{"title": "Unit pricing guidance", "url": "https://example.org/unit-pricing"}],
}
ANSWER = "The unit price shows what each box costs for the same amount."


def _timings(text=SCRIPT, pauses=(0.45, 1.0, 0.25, 0.7)):
    result = []
    cursor = 0.15
    for sentence_index, sentence in enumerate(eq.split_sentences(text)):
        for word in sentence.split():
            result.append({"word": word, "start": round(cursor, 3), "end": round(cursor + 0.24, 3)})
            cursor += 0.34
        if sentence_index < len(pauses):
            cursor += pauses[sentence_index]
    return result


class ScriptAndTimingTests(unittest.TestCase):
    def test_five_sentences_map_to_actual_word_boundaries(self):
        words = _timings()
        spans = eq.sentence_timing_spans(SCRIPT, words)
        self.assertEqual(len(spans), 5)
        self.assertEqual(spans[0]["sentence"], eq.split_sentences(SCRIPT)[0])
        self.assertAlmostEqual(spans[0]["start"], words[0]["start"])
        self.assertLess(spans[0]["end"], spans[1]["start"])

    def test_beat_durations_use_pause_boundaries_and_sum_to_video_duration(self):
        words = _timings()
        duration = words[-1]["end"] + 0.8
        durations = eq.five_beat_segment_durations(SCRIPT, words, duration)
        self.assertEqual(len(durations), 5)
        self.assertAlmostEqual(sum(durations), duration, places=2)
        self.assertGreater(max(durations) - min(durations), 0.25)

    def test_sentence_mapping_rejects_transcript_mismatch(self):
        words = _timings().copy()
        words[2] = {**words[2], "word": "unrelated"}
        with self.assertRaisesRegex(ValueError, "does not match verified word timings"):
            eq.sentence_timing_spans(SCRIPT, words)

    def test_early_answer_uses_actual_boundary_not_estimated_script_position(self):
        words = _timings()
        answer = eq.first_answer_time(SCRIPT, words, ANSWER)
        self.assertIsNotNone(answer)
        self.assertLessEqual(answer, 6.0)
        self.assertGreater(answer, 0)

    def test_missing_measured_answer_phrase_cannot_fall_back_to_estimated_timing(self):
        words = _timings()
        words[11] = {**words[11], "word": "different"}
        self.assertIsNone(eq.first_answer_time(SCRIPT, words, "The unit price shows"))

    def test_script_evidence_title_and_five_queries_pass(self):
        issues = eq.validate_script(SCRIPT, TITLE, TOPIC, QUERIES, ANSWER, EVIDENCE)
        self.assertEqual(issues, [])
        self.assertTrue(eq.title_matches_script(TITLE, SCRIPT, TOPIC))

    def test_explicit_tts_directions_are_detected(self):
        leaks = [
            "Read this in a warm, curious tone. ",
            "Read in a friendly, natural voice. ",
            "Use a calm conversational tone. ",
            "Speak in a warm, curious tone. ",
            "Say this warmly and curiously. ",
            "Narrate it with a calm voice. ",
            "Deliver it in a wry, understated delivery. ",
            "Sound playful and natural. ",
            "Warm, curious tone. ",
            "Style prompt: warm and curious. ",
        ]
        for leak in leaks:
            with self.subTest(leak=leak):
                self.assertTrue(eq.contains_spoken_instruction(leak + SCRIPT))
        # A direction on its own line, after real narration, is still a leak.
        self.assertTrue(eq.contains_spoken_instruction(SCRIPT + "\nRead this in a warm tone."))

    def test_ordinary_narration_with_say_read_sound_and_tone_is_not_flagged(self):
        natural = [
            SCRIPT,
            "Scientists say in a study that the wire snaps.",
            "Mechanics read it with a torch before the shift.",
            "Engineers say warmly that the lake is cold.",
            "Read the label with a magnifier to see the unit price.",
            "The warm tone of the bell carries across the yard.",
            "The warm air rises from the vent. Engineers say the wire can break. "
            "The calm lake reflects the sky. A shopper reads the unit price.",
            "The lid sounds loud when it snaps shut. A shopper says nothing and reads the receipt.",
            "The sensor sounds an alarm when the lid opens. The voice coil moves in a warm field.",
        ]
        for line in natural:
            with self.subTest(line=line):
                self.assertFalse(eq.contains_spoken_instruction(line))

    def test_prompt_leak_and_forced_suspense_are_rejected(self):
        leaky = SCRIPT.replace("A shopper lifts", "Use a curious observation as a shopper lifts")
        issues = eq.validate_script(leaky, TITLE, TOPIC, QUERIES, ANSWER, EVIDENCE)
        self.assertIn("tts_instruction_leak_in_script", issues)
        suspense = SCRIPT.replace("The unit price shows", "Wait until the end; the unit price shows")
        issues = eq.validate_script(suspense, TITLE, TOPIC, QUERIES, ANSWER, EVIDENCE)
        self.assertIn("forced_suspense", issues)

    def test_script_generation_and_review_prompts_keep_the_editorial_contract(self):
        prompt_source = Path("scriptgen.py").read_text(encoding="utf-8")
        for requirement in (
            "observed mini-story", "exactly five complete spoken sentences",
            "roughly six seconds", "evidence_record", "narration order",
            "practical implication", "complete ending", "Do not write stage directions",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement.lower(), prompt_source.lower())
        self.assertIn("do not reward delayed answers", prompt_source.lower())
        self.assertIn("rewrite only what is necessary", prompt_source.lower())

    def test_title_must_match_the_spoken_subject(self):
        self.assertFalse(eq.title_matches_script("Why Airport Lines Move Slowly", SCRIPT, TOPIC))
        issues = eq.validate_script(SCRIPT, "Why Airport Lines Move Slowly", TOPIC,
                                    QUERIES, ANSWER, EVIDENCE)
        self.assertIn("title_script_mismatch", issues)

    def test_voice_delivery_thresholds_are_deterministic(self):
        words = _timings()
        issues = eq.voice_delivery_issues(
            transcript_accuracy_value=0.98, duration_seconds=24, word_timings=words,
            pitch_span_semitones=3.0, word_duration_cv=0.2, max_pause_seconds=0.5,
        )
        self.assertEqual(issues, [])
        failures = eq.voice_delivery_issues(
            transcript_accuracy_value=0.6, duration_seconds=40, word_timings=[],
            pitch_span_semitones=0.2, word_duration_cv=0.01, max_pause_seconds=3.0,
            clipping_detected=True,
        )
        self.assertIn("transcript_mismatch", failures)
        self.assertIn("voice_duration_out_of_band", failures)
        self.assertIn("flat_pitch_movement", failures)
        self.assertIn("audio_clipping", failures)


class CaptionAndSkipTests(unittest.TestCase):
    def test_caption_events_are_phrase_level_safe_and_fade_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            timing_path = Path(tmp) / "timings.json"
            ass_path = Path(tmp) / "captions.ass"
            words = _timings()
            timing_path.write_text(json.dumps(words), encoding="utf-8")
            captions.build_ass(str(timing_path), str(ass_path), ["unit price"], accent="gold")
            content = ass_path.read_text(encoding="utf-8")
            self.assertEqual(captions.CAPTION_FADE, "")
            self.assertNotIn("\\fad", content)
            self.assertEqual(captions.validate_ass(str(ass_path), word_timings=words), [])

    def test_caption_validation_detects_width_and_timing_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.ass"
            path.write_text(
                captions.ASS_HEADER
                + "Dialogue: 0,0:00:00.00,0:00:02.00,Word,,0,0,0,,"
                  "one two three four five six seven eight nine ten eleven twelve thirteen "
                  "fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo "
                  "twentythree twentyfour twentyfive\n"
                + "Dialogue: 0,0:00:01.00,0:00:03.00,Word,,0,0,0,,overlap\n",
                encoding="utf-8",
            )
            issues = captions.validate_ass(str(path))
            self.assertIn("caption_events_overlap", issues)
            self.assertIn("caption_width_overflow", issues)

    def test_truncated_render_fails_before_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.mp4"
            path.write_bytes(b"too small")
            issues, metrics = eq.validate_render(path, expected_duration=20)
            self.assertIn("render_missing_or_truncated", issues)
            self.assertEqual(metrics, {})

    def test_skip_reason_is_appended_as_machine_readable_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "skip_reasons.jsonl"
            eq.record_skip_reason(path, episode_id="pilot-1", topic="cereal",
                                 reason="weak footage", phase="reserve")
            eq.record_skip_reason(path, episode_id="pilot-2", topic="queue",
                                 reason="late answer", phase="script")
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["phase"], "reserve")
            self.assertEqual(rows[1]["reason"], "late answer")

    def test_user_rejection_is_a_reserve_failure(self):
        issues = eq.validate_episode_meta({"human_review_status": "rejected"})
        self.assertIn("user_rejected_episode", issues)


if __name__ == "__main__":
    unittest.main()
