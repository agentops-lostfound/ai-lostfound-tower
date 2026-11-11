import json
from pathlib import Path
import tempfile
import unittest

from agents.storage import SLOT_NUMBERS
from robot.db_pose_sequence import sequence_for_target
from tests.sequence_fixtures import expected_sequence


class TaughtSequencePlanTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(Path('robot/config/pick_sequences.json').read_text(encoding='utf-8'))
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'sequences.json'

    def plan(self, n):
        self.path.write_text(json.dumps(self.config), encoding='utf-8')
        slot = next(s for s, number in SLOT_NUMBERS.items() if number == n)
        return sequence_for_target({'ok': True, 'slot_id': slot, 'pose_name': f'pose_{n}', 'number': n},
                                   sequence_path=self.path)

    def test_all_eight_sequences_start_and_end_at_home_and_include_grasp(self):
        for n in range(1, 9):
            with self.subTest(n=n):
                self.assertEqual(self.plan(n), expected_sequence(n))
                self.assertEqual(len(self.plan(n)), 11)

    def test_all_routes_use_common_return_and_outlet_names(self):
        for n in range(1, 9):
            plan = self.plan(n)
            self.assertEqual(plan.count('outlet_return_1'), 2)
            self.assertIn('close', plan)
            self.assertEqual(plan[5], f'pose_{n}')
            self.assertFalse(any(name.endswith('_78') or name.endswith('_return') for name in plan))

    def test_incomplete_or_reteach_pending_step_is_rejected(self):
        step = self.config['sequences']['pose_1_pick']['steps'][1]
        for change in ({'captured': False}, {'captured': 1}, {'requires_reteach': True}):
            saved = dict(step)
            step.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.plan(1)
            step.clear()
            step.update(saved)

    def test_stale_full_sequence_and_wrong_return_are_rejected(self):
        profile = self.config['sequences']['pose_7_pick']
        profile['full_sequence'] = ['home']
        with self.assertRaises(ValueError):
            self.plan(7)
        profile.pop('full_sequence')
        profile['steps'][3]['pose_name'] = 'pose_7_return'
        with self.assertRaises(ValueError):
            self.plan(7)

    def test_missing_profile_wrong_slot_or_outlet_is_rejected(self):
        profile = self.config['sequences']['pose_8_pick']
        profile['outlet_sequence'] = ['home']
        with self.assertRaises(ValueError):
            self.plan(8)
        profile.pop('outlet_sequence')
        profile['slot_id'] = 'R1-1'
        with self.assertRaises(ValueError):
            self.plan(8)
        self.config['sequences'].pop('pose_8_pick')
        with self.assertRaises(ValueError):
            self.plan(8)
