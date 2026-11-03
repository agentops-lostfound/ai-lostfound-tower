"""가짜 보관함 시나리오(tools/mock_scene.py)와 탑뷰 결과 파일 스위치(TOWER_VISION_FILE) 시험."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import validate_detection  # noqa: E402
from agents.vision_adapter import SequenceFileVisionPart, adapt_report, vision_part_from_env  # noqa: E402
from tools import mock_scene as ms  # noqa: E402


class SceneTest(unittest.TestCase):
    def test_report_shape_and_truth(self):
        report, truth = ms.build_report()
        in_bin = [k for k, v in ms.ITEMS.items() if v.get("bin", v["reg"]) is not None]
        self.assertEqual(sorted(truth.values()), sorted(in_bin))
        dets = adapt_report(report)
        self.assertEqual(len(dets), len(in_bin))
        for d in dets:
            self.assertEqual(validate_detection(d), [])

    def test_item_ids_follow_contract(self):
        from agents.contracts import ITEM_ID_RE
        self.assertTrue(all(ITEM_ID_RE.match(k) for k in ms.ITEMS))

    def test_cases_results(self):
        results = {r["case_id"]: r for r in ms.run_all()}
        self.assertEqual(set(results), {c[0] for c in ms.CASES})
        for cid, r in results.items():
            if cid in ms.KNOWN_GAPS:
                continue
            self.assertTrue(r["ok"], f"{cid}: {r['decision']} ({r['reason']})")
        # 직원 확인으로 넘어간 사례는 로봇이 움직이지 않아야 한다
        for cid in ("S06", "S08"):
            self.assertFalse(results[cid]["robot_moved"], cid)
        self.assertIn("다시 집기", ms.CASES[6][1])
        self.assertIn("집기 성공", results["S07"]["steps"])

    def test_known_gap_is_reported_not_hidden(self):
        r = {x["case_id"]: x for x in ms.run_all()}["S05"]
        text = ms.table([r])
        if not r["ok"]:
            self.assertIn("알려진 한계", text)
            if r["decision"] == "wrong_object":
                self.assertIn("반드시 해결", text)

    def test_write_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ms.main(["--write", tmp]), 0)
            self.assertTrue((Path(tmp) / "mock_scene" / "result_with_qwen.json").is_file())


class VisionSwitchTest(unittest.TestCase):
    def test_env_parsing(self):
        self.assertIsNone(vision_part_from_env({}))
        self.assertIsNone(vision_part_from_env({"TOWER_VISION_FILE": "  "}))
        p = vision_part_from_env({"TOWER_VISION_FILE": "x", "TOWER_VISION_MAX_AGE": "0"})
        self.assertIsInstance(p, SequenceFileVisionPart)
        self.assertIsNone(p.max_age_s)
        self.assertEqual(vision_part_from_env({"TOWER_VISION_FILE": "x", "TOWER_VISION_MAX_AGE": "abc"}).max_age_s, 600.0)

    def test_mcp_default_backend(self):
        from agents.mcp_server import default_backend
        from agents.tools import MockBackend
        self.assertIsInstance(default_backend({}), MockBackend)
        be = default_backend({"TOWER_VISION_FILE": "x"})
        self.assertEqual(be.sources()["vision_topview"], "SequenceFileVisionPart")
        self.assertEqual(be.sources()["db_get_item"], "가짜")

    def test_api_service_uses_file(self):
        from agents import api
        with tempfile.TemporaryDirectory() as tmp:
            path = ms.write_report(tmp)
            env = {"TOWER_VISION_FILE": str(path.parent), "TOWER_VISION_MAX_AGE": "0", "TOWER_DB": "0", "TOWER_SEND": "0"}
            with mock.patch.dict(os.environ, env), mock.patch("tools.envfile.load_env", lambda *a, **k: None):
                svc = api.build_service()
                be = svc.backend_factory()
                self.assertEqual(be.sources()["vision_topview"], "SequenceFileVisionPart")
                self.assertEqual(len(be.vision_topview()), 6)
                self.assertIsNotNone(be.db_get_item("A-W01"))       # 시연 DB(가짜)는 그대로
                # 직접 넘긴 부품(시험용)에는 끼우지 않는다
                svc2 = api.build_service(backend_factory=lambda: "직접")
                self.assertEqual(svc2.backend_factory(), "직접")


if __name__ == "__main__":
    unittest.main()
