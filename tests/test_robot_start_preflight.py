"""시작 전 점검이 토크/보정을 쓰지 않고 raw 목표만 맞추는지 시험."""
from dataclasses import asdict, dataclass
from pathlib import Path
import tempfile
import unittest

from tools.robot_start_preflight import inspect_bus, NAMES


@dataclass
class Calibration:
    id: int
    drive_mode: int = 0
    homing_offset: int = 0
    range_min: int = 800
    range_max: int = 3200


class FakeBus:
    def __init__(self):
        self.calibration = {name: Calibration(i+1) for i, name in enumerate(NAMES)}
        self.data = {name: {"Torque_Enable": 0, "Operating_Mode": 0,
                           "Present_Position": 2000+i, "Goal_Position": 1000}
                     for i, name in enumerate(NAMES)}
        self.writes = []

    def read_calibration(self):
        return self.calibration

    def ping(self, name):
        return 777

    def read(self, register, name, normalize=False):
        return self.data[name][register]

    def write(self, register, name, value, normalize=False):
        if register != "Goal_Position" or normalize:
            raise AssertionError("raw 목표 이외의 쓰기 금지")
        self.writes.append((register, name, value))
        self.data[name][register] = value


class StartPreflightTests(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.expected = {name: asdict(cal) for name, cal in self.bus.calibration.items()}

    def test_read_only_preserves_goal_and_torque(self):
        result = inspect_bus(self.bus, self.expected)
        self.assertEqual(result["result"], "PREFLIGHT_READ_ONLY_OK")
        self.assertEqual(self.bus.writes, [])
        self.assertEqual(result["joints"]["shoulder_pan"]["goal_delta_ticks"], -1000)

    def test_sync_backs_up_and_writes_only_raw_current_position(self):
        with tempfile.TemporaryDirectory() as folder:
            result = inspect_bus(self.bus, self.expected, sync_goal=True, backup_dir=folder)
            self.assertTrue(Path(result["backup"]).is_file())
        self.assertEqual(result["result"], "GOAL_SYNCED_TORQUE_OFF")
        self.assertEqual(len(self.bus.writes), 6)
        for name, state in result["joints"].items():
            self.assertEqual(state["torque"], 0)
            self.assertEqual(state["goal_delta_ticks"], 0)

    def test_torque_on_or_unexpected_mode_blocks_all_writes(self):
        for register, value in (("Torque_Enable", 1), ("Operating_Mode", 1)):
            bus = FakeBus()
            bus.data[NAMES[-1]][register] = value
            with self.assertRaises(RuntimeError):
                inspect_bus(bus, self.expected, sync_goal=True, backup_dir="unused")
            self.assertEqual(bus.writes, [])

    def test_changed_calibration_blocks_all_writes(self):
        self.bus.calibration[NAMES[0]].homing_offset = 200
        with self.assertRaises(RuntimeError):
            inspect_bus(self.bus, self.expected, sync_goal=True, backup_dir="unused")
        self.assertEqual(self.bus.writes, [])

    def test_movement_during_sync_is_reported_without_enabling_torque(self):
        original_write = self.bus.write
        def moving(register, name, value, normalize=False):
            original_write(register, name, value, normalize=normalize)
            self.bus.data[name]["Present_Position"] += 10
        self.bus.write = moving
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "자세 변화"):
                inspect_bus(self.bus, self.expected, sync_goal=True, backup_dir=folder)
        self.assertTrue(all(state["Torque_Enable"] == 0 for state in self.bus.data.values()))
