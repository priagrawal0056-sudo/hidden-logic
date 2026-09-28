import copy
import json
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from credible.storyboard import draw_storyboard, layout_storyboard, validate_storyboard


FIXTURES = Path(__file__).parent / 'fixtures/freezer_storyboard_layout_failures.json'


class StoryboardScenePositionTests(unittest.TestCase):
    def cases(self):
        return json.loads(FIXTURES.read_text())

    def test_latest_live_drafts_keep_all_objects_and_fit_stock_opening(self):
        for case in self.cases():
            with self.subTest(at=case['at']):
                original = copy.deepcopy(case['plan'])
                plan, changes = layout_storyboard(original)
                self.assertEqual(original, case['plan'])
                self.assertTrue(validate_storyboard(plan, opening_is_stock=True))
                with self.assertRaisesRegex(ValueError, 'object count'):
                    validate_storyboard(plan)
                for before, after in zip(original, plan):
                    self.assertEqual(len(before['objects']), len(after['objects']))
                    self.assertEqual([o.get('text') for o in before['objects']],
                                     [o.get('text') for o in after['objects']])
                    for old, new in zip(before['objects'], after['objects']):
                        if old['type'] != 'text':
                            self.assertEqual(old['box'][2:], new['box'][2:])
                    for phase in (0, .25, .55, .99):
                        image = Image.new('RGB', (540, 960), 'black')
                        draw_storyboard(ImageDraw.Draw(image), after, phase)
                        self.assertGreater(len(image.getcolors(540 * 960)), 1)
                translations = [c for c in changes if c.get('reason') == 'scene_translation']
                if case['reason'] == 'Drawing outside safe area':
                    self.assertEqual(len(translations), sum(len(s['objects']) for s in original))
                    self.assertTrue(all(c['translation'] == [-90, 60] for c in translations))
                    self.assertEqual(plan[0]['objects'][0]['box'], [160, 210, 180, 260])
                else:
                    self.assertFalse(translations)
                again, second_changes = layout_storyboard(plan)
                self.assertEqual(again, plan)
                self.assertFalse(second_changes)

    def test_opening_allowance_does_not_weaken_rendered_states_or_geometry(self):
        plan, _ = layout_storyboard(self.cases()[0]['plan'])
        for index in (1, 2, 3):
            invalid = copy.deepcopy(plan)
            invalid[index]['objects'] = copy.deepcopy(plan[0]['objects'])
            with self.subTest(scene=index), self.assertRaisesRegex(ValueError, 'object count'):
                validate_storyboard(invalid, opening_is_stock=True)
        invalid = copy.deepcopy(plan)
        invalid[0]['objects'] = [
            {'type': 'text', 'box': [100, 250, 100, 30], 'text': 'Closed', 'size': 24, 'color': 'ink'},
            {'type': 'text', 'box': [100, 290, 100, 30], 'text': 'Door', 'size': 24, 'color': 'ink'},
        ]
        with self.assertRaisesRegex(ValueError, 'not a demonstration'):
            validate_storyboard(invalid, opening_is_stock=True)
        invalid = copy.deepcopy(plan)
        invalid[1]['objects'][1] = copy.deepcopy(invalid[0]['objects'][1])
        invalid[1]['objects'][1]['box'][1] = 500
        with self.assertRaisesRegex(ValueError, 'not a demonstration'):
            validate_storyboard(invalid, opening_is_stock=True)

    def test_translation_preserves_motion_rotation_signed_paths_and_absolute_endpoints(self):
        plan, _ = layout_storyboard(self.cases()[0]['plan'])
        objects = [
            {'type': 'rect', 'box': [0, 0, 40, 40], 'rotate': 45, 'color': 'panel',
             'motion_path': [[0, 0], [200, 220]]},
            {'type': 'ellipse', 'box': [20, 70, 30, 30], 'move': [30, 20], 'color': 'warm'},
            {'type': 'arrow', 'box': [120, 50, -20, 0], 'end': [-30, 45],
             'move': [-10, 0], 'color': 'accent'},
            {'type': 'text', 'box': [0, 130, 100, 30], 'text': 'Closed', 'size': 24, 'color': 'ink'},
        ]
        plan[1]['objects'] = copy.deepcopy(objects)
        fitted, changes = layout_storyboard(plan)
        self.assertTrue(validate_storyboard(fitted, opening_is_stock=True))
        translations = [c for c in changes if c.get('reason') == 'scene_translation']
        dx, dy = translations[0]['translation']
        self.assertEqual(dx, 78)
        self.assertAlmostEqual(dy, 210 - (20 - 20 * 2 ** .5))
        self.assertEqual(len(translations), len(objects))
        for before, after in zip(objects, fitted[1]['objects']):
            expected = copy.deepcopy(before)
            expected['box'][:2] = [before['box'][0] + dx, before['box'][1] + dy]
            if 'end' in expected:
                expected['end'] = [before['end'][0] + dx, before['end'][1] + dy]
            if 'motion_path' in expected:
                expected['motion_path'] = [[x + dx, y + dy] for x, y in before['motion_path']]
            self.assertEqual(expected, after)

    def test_scene_that_cannot_fit_is_rejected_without_clipping_or_scaling(self):
        for geometry in (
            {'type': 'rect', 'box': [0, 200, 423, 100], 'color': 'ink'},
            {'type': 'rect', 'box': [40, 200, 100, 471], 'color': 'ink'},
            {'type': 'rect', 'box': [40, 250, 80, 80], 'move': [400, 0], 'color': 'ink'},
            {'type': 'rect', 'box': [50, 250, 20, 20],
             'motion_path': [[0, 250], [430, 250]], 'color': 'ink'},
            {'type': 'rect', 'box': [100, 250, 340, 340], 'rotate': 45, 'color': 'ink'},
        ):
            plan = self.cases()[0]['plan']
            plan[1]['objects'].append(geometry)
            original = copy.deepcopy(plan)
            with self.subTest(geometry=geometry), self.assertRaisesRegex(ValueError, 'cannot fit'):
                layout_storyboard(plan)
            self.assertEqual(original, plan)

    def test_direct_validation_still_rejects_unsafe_motion_path_rotation(self):
        plan, _ = layout_storyboard(self.cases()[0]['plan'])
        plan[1]['objects'].append({'type': 'rect', 'box': [100, 300, 80, 80],
                                  'rotate': 45, 'motion_path': [[100, 300], [38, 300]],
                                  'color': 'ink'})
        with self.assertRaisesRegex(ValueError, 'Motion path outside safe area'):
            validate_storyboard(plan, opening_is_stock=True)

    def test_rotated_boundary_roundoff_is_corrected_without_relaxing_validation(self):
        plan, _ = layout_storyboard(self.cases()[0]['plan'])
        x, y = -197.10304185792768, 93.11417873376098
        plan[1]['objects'] = [
            {'type': 'rect', 'box': [x, y, 80, 80], 'rotate': -21.658138710479314, 'color': 'ink'},
            {'type': 'ellipse', 'box': [x + 80, y + 100, 40, 40], 'color': 'warm'},
            {'type': 'text', 'box': [x, y + 150, 100, 30], 'text': 'Closed', 'size': 24, 'color': 'ink'},
        ]
        fitted, _ = layout_storyboard(plan)
        self.assertTrue(validate_storyboard(fitted, opening_is_stock=True))
        fitted[0]['objects'][0]['box'][0] = 38 - 1e-10
        with self.assertRaisesRegex(ValueError, 'Drawing outside safe area'):
            validate_storyboard(fitted, opening_is_stock=True)
