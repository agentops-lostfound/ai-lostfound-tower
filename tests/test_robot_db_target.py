"""DB 칸 모드 — 탑뷰 없이 보관함 정답지(DB)의 칸·번호(1357/2468)·저장 자세로 로봇팔을 보냄 (LF-8 · 11/9 변재원)

한줄 설명: 물건 번호 → 칸 → 번호 1~8 → pose_N 이 맞게 이어지는지, 칸·자세가 없으면 로봇을 움직이지 않는지 확인한다.
안내 docs/contracts/robot_db_target.md
"""
import os
import unittest
from unittest import mock

from agents.storage import SLOT_NUMBERS, SLOT_POSES, MemoryStorageStore, robot_target, robot_targets
from agents.supervisor import DECISION_RETURNED, DECISION_STAFF, ReturnRequest, run_return
from agents.tools import MockBackend


class Rep:
    def __init__(self):
        self.lines = []

    def progress(self, *a):
        self.lines.append(("progress",) + a)

    def alert(self, *a):
        self.lines.append(("alert",) + a)


def store(db, poses=SLOT_POSES):
    return MemoryStorageStore(item_lookup=lambda i: db.get(i), poses=poses)


class NumberingTest(unittest.TestCase):
    def test_1357_far_2468_near_and_pose_n(self):
        far = [s for s, n in SLOT_NUMBERS.items() if n % 2]
        near = [s for s, n in SLOT_NUMBERS.items() if not n % 2]
        self.assertEqual(far, ["R1-1", "R2-1", "R3-1", "R4-1"])       # 11/11 실물: -1 = 먼 칸(탑뷰 위, 왼쪽 위가 1)
        self.assertEqual(near, ["R1-2", "R2-2", "R3-2", "R4-2"])
        for slot, n in SLOT_NUMBERS.items():                             # 번호 N = 저장 자세 pose_N (013 마이그레이션)
            self.assertEqual(SLOT_POSES[slot], f"pose_{n}")

    def test_sim_world_top_left_is_1(self):
        """11/11 실물 확인: 탑뷰 왼쪽 위가 1번(R1-1), 그 아래가 2번 — 가상 세계 그림도 같은 배치(로봇은 아래, y 큼)"""
        from agents.sim_world import ROBOT_BASE_MM, SLOT_IDS, SLOTS_MM
        pos = dict(zip(SLOT_IDS, SLOTS_MM))
        for col in ("R1", "R2", "R3", "R4"):
            self.assertLess(pos[col + "-1"][1], pos[col + "-2"][1])            # -1 이 위(로봇에서 먼 쪽)
            self.assertGreater(ROBOT_BASE_MM[1], pos[col + "-2"][1])
        self.assertEqual(min(SLOTS_MM, key=lambda xy: (xy[1], xy[0])), pos["R1-1"])   # 맨 위 왼쪽 = R1-1

    def test_table_has_8_rows_in_number_order(self):
        rows = robot_targets(store({}).layout())
        self.assertEqual([r["number"] for r in rows], list(range(1, 9)))
        self.assertEqual([r["row"] for r in rows[:2]], ["far", "near"])
        self.assertEqual(rows[6]["slot_id"], "R4-1")
        self.assertTrue(all(r["pose_name"] == r["pose_expected"] for r in rows))


class TargetTest(unittest.TestCase):
    def setUp(self):
        self.db = {"A-W11": {"status": "본센터 보관", "category": "보조배터리"},
                   "A-W12": {"status": "본센터 보관", "category": "지갑"}}

    def test_item_in_slot_gives_pose(self):
        s = store(self.db)
        s.assign("A-W11", "R2-2")
        t = robot_target(s.layout(), "A-W11")
        self.assertTrue(t["ok"])
        self.assertEqual((t["slot_id"], t["number"], t["row"], t["column"], t["pose_name"]),
                         ("R2-2", 4, "near", "R2", "pose_4"))
        self.assertEqual(t["warnings"], [])
        self.assertEqual(t["outlet_sequence"][-1], "home")

    def test_no_slot_no_pose_staff_shelf(self):
        s = store(self.db, poses={})                     # 티칭 전: 자세 이름 없음
        self.assertEqual(robot_target(s.layout(), "A-W11")["code"], "no_slot")
        s.assign("A-W11", "R2-1")
        t = robot_target(s.layout(), "A-W11")
        self.assertEqual((t["ok"], t["code"], t["pose_expected"]), (False, "no_pose", "pose_3"))
        s.move_to_shelf("A-W12")
        self.assertEqual(robot_target(s.layout(), "A-W12")["code"], "staff_shelf")

    def test_renamed_pose_warns(self):
        s = store(self.db)
        s.assign("A-W12", "R4-1")
        s.set_pose("R4-1", "shelf_r4_1")
        t = robot_target(s.layout(), "A-W12")
        self.assertTrue(t["ok"])
        self.assertEqual(t["pose_name"], "shelf_r4_1")
        self.assertIn("pose_7", t["warnings"][0])


class FlowTest(unittest.TestCase):
    def be(self):
        b = MockBackend()
        b.db["A-1"] = {"status": "승인·수령 예약", "features": {"category": "지갑"}}
        return b

    def target(self, **kw):
        t = {"ok": True, "slot_id": "R2-1", "number": 3, "pose_name": "pose_3"}
        t.update(kw)
        return t

    def test_db_mode_moves_by_pose_without_topview(self):
        b = self.be()
        out = run_return(ReturnRequest("C-1", "A-1", robot_target=self.target()), b, Rep())
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertNotIn("vision_topview", b.calls)                       # 탑뷰를 부르지 않음
        self.assertNotIn("robot_approach", b.calls)
        self.assertEqual(b.last_pose, ("pose_3", "R2-1"))
        self.assertIn("DB 칸 위치 사용(탑뷰 없음)", out.steps)

    def test_no_pose_does_not_move(self):
        b = self.be()
        out = run_return(ReturnRequest("C-2", "A-1", robot_target={"ok": False, "code": "no_pose", "reason": "자세 없음"}),
                         b, Rep())
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(any(c.startswith("robot_") for c in b.calls))
        self.assertEqual(b.db["A-1"]["status"], "본센터 보관")            # 움직이기 전 끝 → 보관 상태로 되돌림

    def test_robot_without_go_pose_does_not_move(self):
        from agents.backends import CompositeBackend

        class Robot:            # 6개 필수 함수만 있고 robot_go_pose 는 없는 진짜 부품
            def __getattr__(self, n):
                if n.startswith("robot_") and n != "robot_go_pose":
                    return lambda *a, **k: {"ok": True, "reason": ""}
                raise AttributeError(n)
        fb = self.be()
        b = CompositeBackend(robot=Robot(), fallback=fb)
        out = run_return(ReturnRequest("C-3", "A-1", robot_target=self.target()), b, Rep())
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertIn("robot_go_pose 없음", out.reason)
        self.assertNotIn("robot_go_pose", fb.calls)                       # 가짜 부품으로 '성공'하지 않음

    def test_go_pose_fail_stops(self):
        b = self.be()
        b.approach_ok = False
        out = run_return(ReturnRequest("C-4", "A-1", robot_target=self.target()), b, Rep())
        self.assertIn("저장 자세 이동 실패(pose_3)", out.reason)
        self.assertIn("robot_stop", b.calls)

    def test_vision_mode_unchanged(self):
        b = self.be()
        out = run_return(ReturnRequest("C-5", "A-1"), b, Rep())
        self.assertIn("vision_topview", b.calls)
        self.assertNotIn("robot_go_pose", b.calls)
        self.assertNotIn("DB 칸 위치 사용(탑뷰 없음)", out.steps)


class ServiceModeTest(unittest.TestCase):
    def test_env_switch(self):
        from agents.service import robot_target_mode
        with mock.patch.dict(os.environ, {"TOWER_ROBOT_TARGET": "db"}):
            self.assertEqual(robot_target_mode(), "db")
        with mock.patch.dict(os.environ, {"TOWER_ROBOT_TARGET": "이상한값"}):
            self.assertEqual(robot_target_mode(), "vision")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOWER_ROBOT_TARGET", None)
            self.assertEqual(robot_target_mode(), "vision")

    def test_request_body_cannot_set_target(self):
        from agents.service import GATE_FIELDS
        self.assertNotIn("robot_target", GATE_FIELDS)


class FakeTowerRobot:
    """TOWER_ROBOT_PART 시험용 부품(필수 6개 + robot_go_pose)"""
    def __init__(self):
        self.calls = []

    def _ok(self, name):
        self.calls.append(name)
        return {"ok": True, "reason": ""}

    def robot_approach(self, center_mm, center_px): return self._ok("robot_approach")
    def robot_go_pose(self, pose_name, slot_id): return self._ok(f"robot_go_pose:{pose_name}:{slot_id}")
    def robot_grasp(self): return self._ok("robot_grasp")
    def robot_verify_grasp(self): return self._ok("robot_verify_grasp")
    def robot_deliver(self): return self._ok("robot_deliver")
    def robot_stop(self): return self._ok("robot_stop")
    def robot_home(self): return self._ok("robot_home")


class HalfRobot:
    def robot_stop(self): return {"ok": True, "reason": ""}


class RobotPartEnvTest(unittest.TestCase):
    def test_load_and_route(self):
        from agents.backends import CompositeBackend
        from agents.robot_part import load_robot_part
        part = load_robot_part("tests.test_robot_db_target:FakeTowerRobot")
        fb = MockBackend()
        fb.db["A-W11"] = {"status": "승인·수령 예약", "features": {"category": "지갑"}}
        be = CompositeBackend(robot=part, fallback=fb)
        t = {"ok": True, "slot_id": "R4-2", "number": 8, "pose_name": "pose_8"}
        out = run_return(ReturnRequest("C-9", "A-W11", robot_target=t), be, Rep())
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertEqual(part.calls[:2], ["robot_go_pose:pose_8:R4-2", "robot_grasp"])
        self.assertNotIn("robot_go_pose", fb.calls)

    def test_bad_spec_and_missing(self):
        from agents.robot_part import RobotPartError, load_robot_part, robot_part_from_env
        for spec in ("robot.tower_part", "a b:C", "tests.없는모듈:X", "tests.test_robot_db_target:없음"):
            with self.assertRaises(RobotPartError, msg=spec):
                load_robot_part(spec)
        with self.assertRaises(RobotPartError) as cm:
            load_robot_part("tests.test_robot_db_target:HalfRobot")
        self.assertIn("robot_grasp", str(cm.exception))
        with mock.patch.dict(os.environ, {"TOWER_ROBOT_PART": ""}):
            self.assertIsNone(robot_part_from_env())


if __name__ == "__main__":
    unittest.main()
