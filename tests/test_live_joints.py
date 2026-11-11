"""11/11 실물 팔로워 관절로 가상 팔 그리기(agents/live_joints.py) — 로봇 PC GET /v1/joints(김건태 LF-21) 확정 응답 기준.
로봇 PC·네트워크 없이 가짜 robot.request 로 시험한다"""
import json
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import live_joints as lj  # noqa: E402
from agents.sim_world import SLOTS_MM, SLOT_IDS, SimWorld, so101_tip  # noqa: E402

# 11/11 김건태님 전달 보정값(팔로워) — 비밀값 아님. Studio/LeRobot 각도 변환(robot/vendor_coordinates.py 와 같은 식)
CAL = {"shoulder_pan": (757, 3481), "shoulder_lift": (891, 3277), "elbow_flex": (704, 2921),
       "wrist_flex": (990, 3340), "wrist_roll": (0, 4095)}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def studio_degrees(normalized: dict) -> dict:
    out = {}
    for j, (lo, hi) in CAL.items():
        t = round(lo + (normalized[j + ".pos"] + 100) / 200 * (hi - lo))
        out[j + ".pos"] = (t - (lo + hi) / 2) * 360 / 4095
    out["gripper.pos"] = normalized["gripper.pos"]
    return out


# 확정 응답 예시(관측값, 실제 home 근처)
SAMPLE = {"available": True, "instance": "i-1", "unit": "normalized",
          "positions": {"shoulder_pan.pos": -3.5976505279541016, "shoulder_lift.pos": -99.32942199707031,
                        "elbow_flex.pos": 99.36851501464844, "wrist_flex.pos": -98.38298034667969,
                        "wrist_roll.pos": 9.743589401245117, "gripper.pos": 4.438466548919678},
          "degrees": {"shoulder_pan.pos": -4.3076923076923075, "shoulder_lift.pos": -104.17582417582418,
                      "elbow_flex.pos": 96.83516483516483, "wrist_flex.pos": -101.62637362637362,
                      "wrist_roll.pos": 17.53846153846154, "gripper.pos": 4.438466548919678},
          "read_at": "2026-11-11T08:34:35.144062+00:00", "source": "studio_observation"}


class FakeRobot:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def request(self, path, body=None, *, timeout=2):
        self.calls.append((path, body))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class ConvertTest(unittest.TestCase):
    def test_saved_poses_land_near_their_slots(self):
        """그림의 타겟은 해당 칸 60mm 안이고 접근 자세보다 낮다(실측 TCP 높이 판정 아님)."""
        from agents.taught_mirror import pose_slots
        with open(os.path.join(ROOT, "outputs/robot_panel_live/poses.json"), encoding="utf-8-sig") as f:
            poses = json.load(f)
        slots = pose_slots()
        for n in range(1, 9):
            j = lj.to_sim(studio_degrees(poses[f"pose_{n}_target"]))
            x, y, z = so101_tip(j)
            sx, sy = SLOTS_MM[SLOT_IDS.index(slots[f"pose_{n}"])]
            self.assertLess(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5, 60, (n, x, y))
            # Re-taught lip balm target 7 renders at ~65.6mm with this approximate
            # display conversion. Item-specific teaching must not be lowered to
            # satisfy a fixed picture-height assumption. Keep the descent check.
            approach = lj.to_sim(studio_degrees(poses[f"pose_{n}"]))
            self.assertGreaterEqual(z, 0, n)
            self.assertLess(z, so101_tip(approach)[2], n)

    def test_home_observation_is_folded(self):
        j = lj.to_sim(SAMPLE["degrees"])
        self.assertLess(j["shoulder_lift"], -80)                   # 위팔이 뒤로 누움
        self.assertGreater(j["elbow_flex"], 60)                     # 아래팔이 그 위로 접힘
        self.assertGreater(so101_tip(j)[2], 150)                    # 집게가 위
        self.assertEqual(j["gripper"], 4.4)                         # 집게는 도가 아니라 0~100 그대로

    def test_bad_degrees(self):
        self.assertIsNone(lj.to_sim(None))
        self.assertIsNone(lj.to_sim({**SAMPLE["degrees"], "elbow_flex.pos": None}))
        self.assertIsNone(lj.to_sim({**SAMPLE["degrees"], "elbow_flex.pos": float("nan")}))
        self.assertIsNone(lj.to_sim({**SAMPLE["degrees"], "elbow_flex.pos": True}))


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.w = SimWorld(speed=0, seed=False)
        self.clock = Clock()

    def make(self, reply):
        self.robot = FakeRobot(reply)
        return lj.LiveJoints(self.robot, self.w, {}, clock=self.clock, sleep=lambda s: None)

    def test_available_draws_follower(self):
        r = self.make(SAMPLE)
        self.assertTrue(r.read_once())
        self.assertEqual(self.robot.calls, [("/v1/joints", None)])    # 읽기(GET)만
        a = self.w.arm
        from agents.sim_world import REST_JOINTS
        self.assertEqual({k: a["joints"][k] for k in ("shoulder_lift", "elbow_flex", "wrist_flex")},
                         {k: REST_JOINTS[k] for k in ("shoulder_lift", "elbow_flex", "wrist_flex")})   # home 근처 → 접힌 대기 자세
        self.assertTrue(a["rest"])
        self.assertEqual(a["live"]["normalized"]["shoulder_lift"], -99.3)
        self.assertTrue(r.fresh())
        self.clock.t += 2
        self.assertFalse(r.fresh())                                    # 1.5초 넘으면 실시간 아님

    def test_away_from_home_uses_converted_angles(self):
        with open(os.path.join(ROOT, "outputs/robot_panel_live/poses.json"), encoding="utf-8-sig") as f:
            n = json.load(f)["pose_5_target"]
        r = self.make({**SAMPLE, "positions": n, "degrees": studio_degrees(n)})
        self.assertTrue(r.read_once())
        self.assertEqual(self.w.arm["joints"], lj.to_sim(studio_degrees(n)))
        self.assertFalse(self.w.arm["rest"])

    def test_unavailable_and_errors(self):
        for reply, why in (({"available": False, "reason": "Studio observation is stale"}, "stale"),
                           ({**SAMPLE, "degrees": None}, "degrees"),
                           (OSError("refused"), "OSError"), ("x", "형식")):
            r = self.make(reply)
            before = dict(self.w.arm["joints"])
            self.assertFalse(r.read_once(), reply)
            self.assertIn(why, r.reason)
            self.assertEqual(self.w.arm["joints"], before)              # 이전 그림을 새 관측으로 쓰지 않음
            self.assertFalse(r.fresh())

    def test_mirror_does_not_overwrite_live_but_still_carries_item(self):
        from agents.sim_world import LOC_BIN, LOC_GRIPPER
        from agents.taught_mirror import TaughtMirror
        m = TaughtMirror(self.w, {}, slots={"pose_5": "R3-1"}, poses={})
        m.live = self.make(SAMPLE)
        m.live.read_once()
        iid = self.w.create({"machine_id": "KIOSK-A", "place_id": None, "place_text": "중앙역", "finder": None, "photo_path": None})["item_id"]
        self.w.items[iid]["category"] = "핸드크림"
        self.w.move(iid, LOC_BIN)
        live_joints = dict(self.w.arm["joints"])
        m.begin({"item_id": iid})
        m.event({"index": 5, "total": 11, "pose_name": "pose_5_close", "event": "stage_arrived"})
        self.assertEqual(self.w.arm["joints"], live_joints)            # 자리는 실물 관절이 정함
        self.assertEqual(self.w.items[iid]["loc"], LOC_GRIPPER)        # 물건 옮기기·단계 표시는 그대로
        self.assertIn("pose_5_close", self.w.arm["phase"])
        self.clock.t += 5                                              # 관측이 끊기면 다시 단계 기록으로 그림
        m.event({"index": 6, "total": 11, "pose_name": "pose_5", "event": "stage_arrived"})
        self.assertNotEqual(self.w.arm["joints"], live_joints)

    def test_switch(self):
        self.assertTrue(lj.enabled({}))
        self.assertFalse(lj.enabled({"TOWER_LIVE_JOINTS": "0"}))


class ApiTest(unittest.TestCase):
    def test_state_says_live_only_while_fresh(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        svc = build_sim_service({"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_AGENT_TALK": "0"})
        fresh = [True]
        svc.taught_robot = True
        svc.robot_mirror = SimpleNamespace(live=SimpleNamespace(fresh=lambda: fresh[0], reason="관측 없음"))
        c = TestClient(build_app(svc))
        st = c.get("/api/admin/live/state").json()
        self.assertEqual(st["world"]["robot"]["telemetry_available"], "live")
        fresh[0] = False
        st = c.get("/api/admin/live/state").json()
        self.assertEqual(st["world"]["robot"]["telemetry_available"], "stage")
        self.assertIn("관측 없음", st["world"]["robot"]["role"])


if __name__ == "__main__":
    unittest.main()
