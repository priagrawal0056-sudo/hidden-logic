"""Pilot batch contract tests; importing the module performs no network work."""
import unittest

import pilot_batch


class PilotBatchTests(unittest.TestCase):
    def test_six_slots_are_balanced_and_directions_are_controlled(self):
        self.assertEqual(len(pilot_batch.PILOT_SPECS), 6)
        counts = {}
        for item in pilot_batch.PILOT_SPECS:
            counts[item["category"]] = counts.get(item["category"], 0) + 1
        self.assertEqual(counts, {
            "technology": 2,
            "queues_travel": 2,
            "shopping_pricing": 2,
        })
        directions = {item["voice_direction"] for item in pilot_batch.PILOT_SPECS}
        self.assertEqual(directions, {
            "curious_observation",
            "understated_dry_amusement",
            "confident_practical_explanation",
        })
        self.assertEqual(len({item["pilot_id"] for item in pilot_batch.PILOT_SPECS}), 6)
        self.assertTrue(all(item["topic"].strip() for item in pilot_batch.PILOT_SPECS))

    def test_default_cli_only_prints_plan_and_does_not_generate(self):
        from unittest import mock
        with mock.patch("sys.argv", ["pilot_batch.py"]):
            self.assertEqual(pilot_batch.main(), 0)


if __name__ == "__main__":
    unittest.main()
