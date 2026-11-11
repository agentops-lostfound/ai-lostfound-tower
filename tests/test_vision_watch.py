"""11/10 사진 분석(Qwen) 과정·결과를 통합 시연 화면에 보여 주는 사건 시험 — agents/vision_watch.py

확인하는 것
- 단계: 사진 접수(queued) → 작업자가 가져감(picked) → 분석 중(analyze) → 결과(result), 걸린 시간
- 결과 사건에는 Qwen 이 읽은 값과 저장한 값이 같이 가고, 비공개 값(읽은 글자·스티커·특이점)은 개수·상태만 간다
- 작업자가 켜져 있는지: 대기 목록을 최근에 물었는지로 판단
- API 한 바퀴: 키오스크 사진 접수 → 대기 목록 → 단계 알림 → 특징 보내기 → /api/admin/live/state?detail=1 에 vision 사건
- Qwen 작업자(tools/intake_qwen_worker.py)가 분석 직전·실패 때 단계를 알리고, 알림이 안 돼도 분석은 계속한다
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import observability  # noqa: E402
from agents.live import LiveBoard  # noqa: E402
from agents.vision_watch import VisionWatch, raw_view, saved_view  # noqa: E402

SECRET_TEXT = "NIVEA-7731"
QWEN = {"category": "hand_cream", "colors": ["white", "blue"], "shape": "tube", "materials": ["plastic"],
        "logos_or_text": [SECRET_TEXT], "sticker_status": "present",
        "stickers": [{"shape": "star", "position": "cap", "colors": ["yellow"]}],
        "distinctive_features": ["뚜껑 옆 긁힘 자국"]}
JPG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 64 + b"\xff\xd9").decode()


def vision_events(board, after=0):
    return [e["vision"] for e in board.since(after, detail=True, limit=9999) if e["channel"] == "vision"]


class ViewTest(unittest.TestCase):
    def test_raw_view_keeps_public_and_counts_private(self):
        v = raw_view(QWEN)
        self.assertEqual((v["category"], v["colors"], v["shape"], v["materials"]), ("hand_cream", ["white", "blue"], "tube", ["plastic"]))
        self.assertEqual((v["logos_or_text"], v["stickers"], v["distinctive_features"]), ("1개 읽음", "1개 있음", "1개"))
        text = json.dumps(v, ensure_ascii=False)
        for secret in (SECRET_TEXT, "star", "긁힘"):
            self.assertNotIn(secret, text)

    def test_raw_view_of_nothing(self):
        v = raw_view(None)
        self.assertEqual((v["category"], v["colors"], v["logos_or_text"], v["stickers"]), ("-", [], "읽은 글자 없음", "알 수 없음"))
        self.assertEqual(raw_view({"sticker_status": "absent"})["stickers"], "없음")

    def test_saved_view_hides_private_values(self):
        from agents.vision_adapter import to_features
        feats = to_features(QWEN, 0.85)
        v = saved_view(feats)
        self.assertEqual(v["confidence"], 0.85)
        self.assertEqual((v["mark"], v["visible_text"]), ("저장됨(값은 가림)", "저장됨(값은 가림)"))
        self.assertEqual(v["category"], feats["category"])
        text = json.dumps(v, ensure_ascii=False)
        for secret in (SECRET_TEXT, "star"):
            self.assertNotIn(secret, text)
        empty = saved_view(to_features({"category": "wallet", "sticker_status": "absent"}, 0.5))
        self.assertEqual((empty["mark"], empty["visible_text"]), ("없음", "확인 불가"))


class WatchTest(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.board = LiveBoard()
        self.w = VisionWatch(self.board, clock=lambda: self.now[0])

    def test_stages_in_order_with_seconds(self):
        self.w.queued("A-1", "KIOSK-A")
        self.now[0] += 3
        self.w.polled([{"item_id": "A-1"}])
        self.w.polled([{"item_id": "A-1"}])                      # 같은 사진이 목록에 또 나와도 '가져감'은 한 번
        self.assertTrue(self.w.stage("A-1", "analyze"))
        self.now[0] += 9.5
        self.w.result("A-1", QWEN, {"category": "핸드크림", "color": "흰색", "mark": "star sticker", "visible_text": SECRET_TEXT, "confidence": 0.85})
        evs = vision_events(self.board)
        self.assertEqual([e["stage"] for e in evs], ["queued", "picked", "analyze", "result"])
        self.assertEqual(evs[0]["machine"], "KIOSK-A")
        self.assertFalse(evs[0]["worker"])                       # 접수 때는 작업자가 아직 물은 적 없음
        self.assertEqual(evs[1]["waited"], 3.0)
        self.assertEqual(evs[3]["seconds"], 12.5)
        self.assertEqual(evs[3]["saved"]["category"], "핸드크림")
        self.assertNotIn(SECRET_TEXT, json.dumps(evs, ensure_ascii=False))
        self.assertEqual(self.board.since(0), [])                # 예전 화면(/live)·봇에는 나가지 않음

    def test_unknown_stage_is_refused(self):
        self.assertFalse(self.w.stage("A-1", "result"))          # 결과는 특징 저장으로만 생긴다
        self.assertFalse(self.w.stage("A-1", "아무거나"))
        self.assertEqual(vision_events(self.board), [])

    def test_worker_alive_by_recent_poll(self):
        self.assertEqual(self.w.worker(), {"on": False, "seen_ago": None})
        self.w.polled([])
        self.now[0] += 5
        self.assertEqual(self.w.worker(), {"on": True, "seen_ago": 5.0})
        self.now[0] += 30
        self.assertFalse(self.w.worker()["on"])

    def test_result_without_queue_and_broken_board(self):
        self.w.result("A-9", QWEN, None)                         # 관제탑을 다시 켠 뒤 온 결과: 걸린 시간만 모름
        self.assertIsNone(vision_events(self.board)[0]["seconds"])

        class Broken:
            def vision(self, data):
                raise RuntimeError("기록판 고장")
        w = VisionWatch(Broken())
        w.queued("A-1")
        w.polled([{"item_id": "A-1"}])
        w.result("A-1", QWEN, {})                                # 사건을 못 남겨도 예외가 밖으로 나오지 않는다


class ApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = build_sim_service({"TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "0", "TOWER_SIM_QWEN_WAIT": "5"})
        self.svc.photo_dir = self.tmp.name                        # 시험 사진은 임시 폴더에(저장소 data/ 를 건드리지 않게)
        self.c = TestClient(build_app(self.svc))

    def tearDown(self):
        observability.set_listener("live-board", None)
        self.tmp.cleanup()

    def state(self, after=0):
        return self.c.get(f"/api/admin/live/state?after={after}&detail=1").json()

    def test_photo_to_features_round(self):
        self.assertFalse(self.state()["qwen_worker"]["on"])
        r = self.c.post("/api/kiosk/items", json={"machine_id": "KIOSK-A", "place_text": "중앙역 승강장", "photo": JPG})
        self.assertEqual(r.status_code, 200, r.text)
        iid = r.json()["item_id"]
        rows = self.c.get("/api/admin/intake/pending-photos").json()
        self.assertIn(iid, [x["item_id"] for x in rows])
        self.assertTrue(self.state()["qwen_worker"]["on"])       # 대기 목록을 물었으니 작업자가 켜진 것으로 보인다
        self.assertEqual(self.c.post(f"/api/admin/intake/analysis/{iid}", json={"stage": "analyze"}).status_code, 200)
        self.assertEqual(self.c.post(f"/api/admin/intake/analysis/{iid}", json={"stage": "result"}).status_code, 422)
        self.assertEqual(self.c.post("/api/admin/intake/analysis/나쁜번호", json={"stage": "analyze"}).status_code, 422)
        r = self.c.post(f"/api/kiosk/items/{iid}/features", json={"qwen": QWEN, "confidence": 0.85})
        self.assertEqual(r.status_code, 200, r.text)
        self.svc.sim.wait_idle(20)

        full = self.state()
        evs = [e["vision"] for e in full["events"] if e["channel"] == "vision" and e["vision"]["item_id"] == iid]
        self.assertEqual([e["stage"] for e in evs], ["queued", "picked", "analyze", "result"])
        res = evs[-1]
        self.assertEqual(res["raw"]["category"], "hand_cream")
        self.assertEqual(res["raw"]["colors"], ["white", "blue"])
        self.assertEqual(res["saved"]["confidence"], 0.85)
        self.assertEqual(res["saved"]["visible_text"], "저장됨(값은 가림)")
        self.assertIsNotNone(res["seconds"])
        # 화면으로 나가는 사건 전체에 비공개 값이 없다(읽은 글자 · 스티커 모양)
        text = json.dumps(full["events"], ensure_ascii=False)
        self.assertNotIn(SECRET_TEXT, text)
        self.assertNotIn("star sticker", text)
        # 저장소 사건: 사진으로 채운 특징은 'Qwen 사진 분석'이 쓴 것으로
        upd = [e["db"] for e in full["events"] if e["channel"] == "db" and e["db"]["table"] == "item" and e["db"]["op"] == "UPDATE"
               and e["db"]["key"] == iid and any(c["name"] == "features" for c in e["db"]["cols"])]
        self.assertTrue(upd and upd[0]["by"] == "Qwen 사진 분석", upd)
        # 예전 화면(/live)·봇에는 vision 사건이 나가지 않는다
        plain = self.c.get("/api/admin/live/state?after=0").json()
        self.assertNotIn("vision", {e["channel"] for e in plain["events"]})
        self.assertNotIn("qwen_worker", plain)

    def test_text_report_is_not_called_qwen(self):
        self.c.post("/sim/found", json={"text": "중앙역 승강장에서 검정 카드지갑 주웠어요"})
        self.svc.sim.wait_idle(20)
        full = self.state()
        self.assertEqual([e for e in full["events"] if e["channel"] == "vision"], [])        # 사진이 없으니 사진 분석 사건도 없다
        by = {e["db"]["by"] for e in full["events"] if e["channel"] == "db" and e["db"]["table"] == "item"
              and any(c["name"] == "features" for c in e["db"]["cols"]) and e["db"]["op"] == "UPDATE"}
        self.assertEqual(by, {"가상 분석(글 신고)"})


class WorkerTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        import intake_qwen_worker as worker
        self.worker = worker
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    def tearDown(self):
        self.tmp.cleanup()

    def tower(self, with_stage=True):
        calls = []

        class T:
            def pending(self, limit=10):
                return [{"item_id": "A-20261110-0001", "machine_id": "KIOSK-A", "photo_path": "a.jpg"}]

            def send(self, item_id, feats):
                calls.append(("send", item_id))
                return {}
        if with_stage:
            T.stage = lambda self, item_id, stage, detail="": calls.append((stage, item_id, detail))
        return T(), calls

    def test_stage_notified_before_analyze_and_on_fail(self):
        t, calls = self.tower()
        order = []
        done = self.worker.process_once(t, lambda p: order.append(list(calls)) or QWEN, {}, log=lambda *a: None, root=Path(self.tmp.name))
        self.assertEqual(done, 1)
        self.assertEqual(order[0][0][:2], ("analyze", "A-20261110-0001"))      # 분석을 시작하기 전에 알림
        self.assertEqual([c[0] for c in calls], ["analyze", "send"])

        t, calls = self.tower()

        def boom(p):
            raise RuntimeError("모델 오류")
        self.assertEqual(self.worker.process_once(t, boom, {}, log=lambda *a: None, root=Path(self.tmp.name)), 0)
        self.assertEqual([c[0] for c in calls], ["analyze", "fail"])
        self.assertIn("RuntimeError", calls[1][2])

    def test_tower_without_stage_still_works(self):
        t, calls = self.tower(with_stage=False)                  # 단계 알림이 없는 연결(옛 시험용 가짜)도 그대로
        self.assertEqual(self.worker.process_once(t, lambda p: QWEN, {}, log=lambda *a: None, root=Path(self.tmp.name)), 1)
        self.assertEqual(calls, [("send", "A-20261110-0001")])

    def test_stage_call_failure_is_swallowed(self):
        t = self.worker.Tower("http://127.0.0.1:9", "")           # 닫힌 포트: 알림 실패
        t.stage("A-20261110-0001", "analyze")                     # 예외 없이 끝나야 한다


if __name__ == "__main__":
    unittest.main()
