"""관제탑 ↔ 로봇팔 계약(agents/robot_api.py, docs/contracts/robot_api.md) — 11/5"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.backends import CompositeBackend, MockBackend  # noqa: E402
from agents.robot_api import (JOINT_NAMES, ROBOT_COMMANDS, check_robot_part, validate_robot_result,  # noqa: E402
                              validate_robot_state)
from agents.sim_world import SO101_JOINTS, SimRobot, SimWorld  # noqa: E402


class RobotContractTest(unittest.TestCase):
    def test_joint_names_match_sim(self):
        self.assertEqual(JOINT_NAMES, tuple(n for n, _ in SO101_JOINTS))

    def test_sim_robot_fulfils_contract(self):
        w = SimWorld(speed=0)
        r = SimRobot(w)
        self.assertEqual(check_robot_part(r), {"missing": [], "has_state": True})
        self.assertEqual(validate_robot_state(r.robot_state()), [])
        self.assertEqual(validate_robot_result(r.robot_stop()), [])
        self.assertTrue(r.robot_state()["stopped"])
        self.assertEqual(validate_robot_result(r.robot_home()), [])
        self.assertFalse(r.robot_state()["stopped"])

    def test_bad_states_are_caught(self):
        good = SimRobot(SimWorld(speed=0)).robot_state()
        self.assertTrue(validate_robot_state({**good, "joints": {"shoulder_pan": 0}}))
        self.assertTrue(validate_robot_state({**good, "stopped": "no"}))
        self.assertTrue(validate_robot_state({**good, "joints": {**good["joints"], "gripper": 150}}))
        self.assertTrue(validate_robot_state({**good, "joints": {**good["joints"], "elbow_flex": float("nan")}}))
        self.assertTrue(validate_robot_result({"ok": "yes"}))

    def test_composite_routes_state_only_from_real_robot(self):
        self.assertIsNone(getattr(CompositeBackend(), "robot_state", None))      # 가짜 부품뿐이면 상태 없음
        sim = SimRobot(SimWorld(speed=0))
        be = CompositeBackend(robot=sim)
        self.assertEqual(be.robot_state()["source"], "sim")
        self.assertEqual(check_robot_part(MockBackend())["missing"], [])
        self.assertEqual(len(ROBOT_COMMANDS), 6)


if __name__ == "__main__":
    unittest.main()
