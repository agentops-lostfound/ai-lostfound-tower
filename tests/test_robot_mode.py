"""11/13 로봇 모드 전환(실물 / 가상) 시험 — tools/robot_mode.py · tools/start_tower.bat 의 sim·real 옵션

확인하는 것
- 판정: 실물 값 5개가 모두 있으면 real, 모두 비면 sim, 일부만 있으면 broken(빠진 이름만 알려 주고 값은 내보내지 않음)
- sim 옵션의 원리: 창에서 공백 한 칸으로 정해 둔 값은 .env 가 덮지 못하고, 관제탑 코드는 그것을 '비어 있음'으로 읽어 가짜 로봇이 된다
- real 옵션: 값이 빠지면 종료 코드 2(관제탑을 켜지 않음)
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import robot_mode  # noqa: E402
from tools.envfile import load_env  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SECRET = "s" * 40
REAL = {"TOWER_ROBOT_SEQUENCE": "taught", "TOWER_ROBOT_TARGET": "db", "TOWER_ROBOT_PART": robot_mode.REAL_PART,
        "TOWER_REMOTE_ROBOT_URL": "http://192.0.2.10:9000", "TOWER_REMOTE_ROBOT_TOKEN": SECRET}
KEYS = [k for k, _ in robot_mode.NEEDS]


class DecideTest(unittest.TestCase):
    def test_real_sim_broken(self):
        self.assertEqual(robot_mode.decide(REAL), ("real", []))
        self.assertEqual(robot_mode.decide({})[0], "sim")
        self.assertEqual(robot_mode.decide({"TOWER_REMOTE_ROBOT_URL": "http://192.0.2.10:9000"})[0], "sim")   # 주소만 남은 것은 가상
        mode, lack = robot_mode.decide({**REAL, "TOWER_REMOTE_ROBOT_TOKEN": ""})
        self.assertEqual(mode, "broken")
        self.assertEqual(lack, ["TOWER_REMOTE_ROBOT_TOKEN(비어 있음)"])
        mode, lack = robot_mode.decide({**REAL, "TOWER_ROBOT_PART": "robot.tower_part:TowerRobot"})
        self.assertEqual(mode, "broken")
        self.assertIn("TOWER_ROBOT_PART", lack[0])

    def test_spaces_mean_virtual(self):
        """sim 옵션이 넣는 공백 한 칸 = 비어 있음"""
        env = {**REAL, "TOWER_ROBOT_SEQUENCE": " ", "TOWER_ROBOT_PART": " ", "TOWER_ROBOT_TARGET": " "}
        self.assertEqual(robot_mode.decide(env)[0], "sim")


class SimOverrideTest(unittest.TestCase):
    """.env 에 실물 값이 있어도 sim 으로 켠 창에서는 관제탑 코드가 가짜 로봇을 고른다"""

    def run_with(self, preset):
        with tempfile.TemporaryDirectory() as tmp:
            envfile = Path(tmp) / ".env"
            envfile.write_text("\n".join(f"{k}={v}" for k, v in REAL.items()), encoding="utf-8")
            clean = {k: v for k, v in os.environ.items() if k not in KEYS}
            with mock.patch.dict(os.environ, {**clean, **preset}, clear=True):
                load_env(envfile)
                from agents import taught_return
                from agents.robot_part import robot_part_from_env
                from agents.service import robot_target_mode
                return robot_mode.decide(os.environ)[0], taught_return.enabled(), robot_part_from_env() is None, robot_target_mode()

    def test_sim_wins_over_env_file(self):
        spaces = {"TOWER_ROBOT_SEQUENCE": " ", "TOWER_ROBOT_PART": " ", "TOWER_ROBOT_TARGET": " "}
        self.assertEqual(self.run_with(spaces), ("sim", False, True, "vision"))

    def test_env_file_alone_is_real(self):
        with mock.patch("agents.robot_part.load_robot_part", return_value=object()):
            mode, taught, fake, target = self.run_with({})
        self.assertEqual((mode, taught, fake, target), ("real", True, False, "db"))


class MainTest(unittest.TestCase):
    def call(self, env, *argv):
        clean = {k: v for k, v in os.environ.items() if k not in KEYS}
        out = io.StringIO()
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), mock.patch("tools.envfile.load_env", return_value={}), redirect_stdout(out):
            code = robot_mode.main(list(argv))
        return code, out.getvalue()

    def test_real_requires_all_values_and_never_prints_them(self):
        code, text = self.call({**REAL, "TOWER_REMOTE_ROBOT_URL": ""}, "real")
        self.assertEqual(code, 2)
        self.assertIn("TOWER_REMOTE_ROBOT_URL(비어 있음)", text)
        self.assertNotIn(SECRET, text)
        code, text = self.call(REAL, "real")
        self.assertEqual(code, 0)
        self.assertIn("실물 로봇 모드", text)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("192.0.2.10", text)

    def test_sim_and_plain(self):
        self.assertIn("가상 로봇 모드", self.call({}, "sim")[1])
        self.assertIn("가상 로봇 모드", self.call({})[1])
        code, text = self.call({**REAL, "TOWER_REMOTE_ROBOT_TOKEN": ""})
        self.assertEqual(code, 0)
        self.assertIn("일부만", text)

    def test_start_script_has_the_switch(self):
        bat = (ROOT / "tools/start_tower.bat").read_text(encoding="utf-8")
        for needle in ('if /i "%%a"=="sim" set TOWER_ROBOT_WANT=sim', 'if /i "%%a"=="real" set TOWER_ROBOT_WANT=real',
                       'set "TOWER_ROBOT_SEQUENCE= "', 'set "TOWER_ROBOT_PART= "', 'set "TOWER_ROBOT_TARGET= "',
                       "python tools\\robot_mode.py %TOWER_ROBOT_WANT%", "if errorlevel 2 goto run_done"):
            self.assertIn(needle, bat)
        self.assertLess(bat.index("python tools\\robot_mode.py"), bat.index("python tools\\run_tower.py"))


if __name__ == "__main__":
    unittest.main()
