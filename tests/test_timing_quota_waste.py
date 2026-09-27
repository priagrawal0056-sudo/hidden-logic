"""Avoid paying for identical narration that already failed measured pacing."""
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from credible.core import read
from credible.pipeline import _check_narration_with_retake, prepare, settings
from credible.rejections import TimingRejected


class TimingQuotaWasteTests(unittest.TestCase):
    def test_long_openings_from_failed_run_do_not_get_unchanged_retakes(self):
        for answer, duration in ((9.76, 27.00), (9.30, 29.36), (9.20, 26.88)):
            episode = {'production_version': 4, 'duration': duration,
                       'first_answer_end': answer, 'beats': ['Complete script.']}
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory, \
                    patch('credible.pipeline.timeline_checks', side_effect=ValueError(
                        'First useful answer must finish within six seconds')), \
                    patch('credible.pipeline.synthesize') as synth:
                with self.assertRaises(TimingRejected):
                    _check_narration_with_retake(episode, Path(directory), settings())
                synth.assert_not_called()
                review = read(Path(directory)/'voice.mp3.timing-review.json')
                self.assertEqual(review['status'], 'needs_script_revision')
                self.assertEqual(review['measurements']['previous_first_answer_end'], answer)

    def test_near_miss_keeps_one_natural_retake_and_measured_gate(self):
        episode = {'production_version': 4, 'duration': 26.14,
                   'first_answer_end': 6.48, 'beats': ['Complete script.']}
        accepted = {**episode, 'first_answer_end': 5.62}
        with tempfile.TemporaryDirectory() as directory, \
                patch('credible.pipeline.timeline_checks', side_effect=[ValueError(
                    'First useful answer must finish within six seconds'), None]) as checks, \
                patch('credible.pipeline.synthesize', return_value=accepted) as synth:
            result = _check_narration_with_retake(episode, Path(directory), settings())
            self.assertEqual(result['first_answer_end'], 5.62)
            self.assertEqual(checks.call_count, 2)
            synth.assert_called_once()

    def test_rejected_identical_take_is_not_regenerated_on_rerun(self):
        episode = {'id': 'same-script', 'production_version': 4, 'beats': ['Long opening.'],
                   'storyboard': [], 'evidence': [], 'source_label': 'Source'}
        def measured(ep, *args):
            return {**ep, 'duration': 27, 'first_answer_end': 9.2}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch('editorial_media.fingerprint', return_value=[]))
            stack.enter_context(patch('config_loader.load_config', return_value={}))
            stack.enter_context(patch('credible.pipeline.script_checks'))
            stack.enter_context(patch('credible.pipeline.timeline_checks', side_effect=ValueError(
                'First useful answer must finish within six seconds')))
            synth = stack.enter_context(patch('credible.pipeline.synthesize', side_effect=measured))
            render = stack.enter_context(patch('credible.pipeline.render'))
            for _ in range(2):
                with self.assertRaises(TimingRejected):
                    prepare(episode, root, settings())
            self.assertEqual(synth.call_count, 1)
            render.assert_not_called()
            # An actual writing change allows a fresh measured attempt.
            with self.assertRaises(TimingRejected):
                prepare({**episode, 'beats': ['Revised opening.']}, root, settings())
            self.assertEqual(synth.call_count, 2)

    def test_interruption_cannot_reset_same_script_retake_budget(self):
        episode = {'id': 'interrupted', 'production_version': 4, 'beats': ['Complete thought.'],
                   'storyboard': [], 'evidence': [], 'source_label': 'Source'}
        initial = {**episode, 'duration': 26.14, 'first_answer_end': 6.48}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch('editorial_media.fingerprint', return_value=[]))
            stack.enter_context(patch('config_loader.load_config', return_value={}))
            stack.enter_context(patch('credible.pipeline.script_checks'))
            stack.enter_context(patch('credible.pipeline.timeline_checks', side_effect=ValueError(
                'First useful answer must finish within six seconds')))
            synth = stack.enter_context(patch('credible.pipeline.synthesize',
                                             side_effect=[initial, KeyboardInterrupt()]))
            with self.assertRaises(KeyboardInterrupt):
                prepare(episode, root, settings())
            with self.assertRaises(TimingRejected):
                prepare(episode, root, settings())
            self.assertEqual(synth.call_count, 2)


if __name__ == '__main__':
    unittest.main()
