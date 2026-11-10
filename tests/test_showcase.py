"""11/10 통합 시연 화면(/showcase) 시험 — 저장소 사건(db)·에이전트 사건(trace)·화면 주소 정리

확인하는 것
- 기록판: db·trace 사건은 since(detail=True) 로 물을 때만 나간다(/live 화면·분실물 봇·관제 분석은 예전 사건만)
- 리스너: 챗봇·메인 AI 단계의 시작/끝이 화면용으로도 나가고, 개인정보 모양은 가려지며, 리스너가 고장 나도 단계는 그대로 돈다
- 저장소 지켜보기: 습득 → 분실 신고 → 키오스크 회수 한 바퀴에서 표·칸 사건이 나오고, 이름·전화번호·신분 번호·비공개 특징 값은 없다
- 주소: /showcase 가 열리고, 옛 주소(/intake·/storage-desk)는 새 주소로 넘긴다
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import db_watch, observability  # noqa: E402
from agents.live import LiveBoard  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV = {"TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "1"}
PHONE = "010-1234-5678"
ID_MASKED = "******-1******"


def sim_service():
    from agents.sim_director import build_sim_service
    return build_sim_service(ENV)


def db_events(board, after=0):
    return [e for e in board.since(after, detail=True, limit=9999) if e["channel"] == "db"]


class BoardDetailTest(unittest.TestCase):
    def test_detail_events_only_when_asked(self):
        b = LiveBoard()
        b.add("progress", "[R1] 탑뷰 촬영", "물건 3개")
        b.db("item", "INSERT", key="A-1", cols=[db_watch.col("status", "등록기계 보관", True)], by="등록기계", label="습득물")
        b.trace({"kind": "start", "name": "planner", "type": "agent"})
        b.add("alert", "[R1] ⚠️ 매칭 실패")
        self.assertEqual([e["channel"] for e in b.since(0)], ["progress", "alert"])          # 예전 화면·봇이 보는 것
        full = b.since(0, detail=True)
        self.assertEqual([e["channel"] for e in full], ["progress", "db", "trace", "alert"])
        self.assertEqual([e["seq"] for e in full], [1, 2, 3, 4])                              # 번호는 한 줄로 이어짐
        self.assertEqual([e["channel"] for e in b.since(2, detail=True)], ["trace", "alert"])
        self.assertEqual(full[1]["db"]["cols"][0], {"name": "status", "label": "상태", "value": "등록기계 보관",
                                                    "changed": True, "hidden": False})

    def test_col_masks_and_cuts(self):
        self.assertEqual(db_watch.col("place_text", f"연락 {PHONE}")["value"], "연락 [전화번호]")
        self.assertEqual(db_watch.col("approved", True)["value"], "예")
        self.assertEqual(db_watch.col("features", {"color": "검정", "confidence": 0.9, "mark": ""})["value"], "색=검정")
        self.assertLessEqual(len(db_watch.col("reason", "가" * 500)["value"]), db_watch.VALUE_LIMIT)


class ListenerTest(unittest.TestCase):
    def setUp(self):
        self.got = []
        observability.set_listener("test", self.got.append)

    def tearDown(self):
        observability.set_listener("test", None)

    def test_steps_reach_listener(self):
        with observability.conversation(session_id="s1", trace_name="lost-found-chatbot"):
            with observability.step("lost-found-chatbot", as_type="chain", input={"question": f"내 번호는 {PHONE}"}) as root:
                with observability.node_step("planner", as_type="agent", input={"question": "지갑"}) as obs:
                    with observability.step("planner-llm", as_type="generation", model="midm", input=[{"role": "system", "content": "비밀 프롬프트"}]) as gen:
                        gen.update(output={"plan": ["item_search"]})
                    obs.update(output={"plan": ["item_search"], "routing": "llm"})
                root.update(output={"answer": "후보 1건"})
        kinds = [(e["kind"], e["name"]) for e in self.got]
        self.assertEqual(kinds, [("trace_start", "lost-found-chatbot"), ("start", "lost-found-chatbot"), ("start", "planner"),
                                 ("start", "planner-llm"), ("end", "planner-llm"), ("end", "planner"),
                                 ("end", "lost-found-chatbot"), ("trace_end", "lost-found-chatbot")])
        by = {(e["kind"], e["name"]): e for e in self.got}
        self.assertEqual(len({e["trace"] for e in self.got}), 1)                              # 질문 하나 = 번호 하나
        self.assertEqual(by[("start", "planner")]["parent"], "lost-found-chatbot")
        self.assertEqual(by[("start", "planner-llm")]["parent"], "planner")
        self.assertEqual(by[("end", "planner")]["output"], 'plan: ["item_search"] · routing: llm')
        self.assertEqual(by[("start", "planner-llm")]["input"], "")                           # 모델 호출 입력(프롬프트 전문)은 내보내지 않음
        self.assertEqual(by[("start", "planner-llm")]["model"], "midm")
        self.assertIsInstance(by[("end", "planner")]["ms"], int)
        blob = json.dumps(self.got, ensure_ascii=False)
        self.assertNotIn(PHONE, blob)
        self.assertNotIn("비밀 프롬프트", blob)
        self.assertIn("[전화번호]", blob)

    def test_error_and_warning_are_reported(self):
        with self.assertRaises(ValueError):
            with observability.node_step("item_search", as_type="tool"):
                raise ValueError("boom")
        with observability.step("llm", as_type="generation", model="m") as gen:
            gen.update(level="WARNING", status_message="TimeoutError")
        ends = [e for e in self.got if e["kind"] == "end"]
        self.assertEqual(ends[0]["error"], "ValueError")
        self.assertEqual(ends[1]["error"], "WARNING: TimeoutError")

    def test_broken_listener_never_blocks(self):
        def bad(_ev):
            raise RuntimeError("화면 고장")
        observability.set_listener("bad", bad)
        try:
            with observability.node_step("planner", as_type="agent") as obs:
                obs.update(output={"plan": []})
        finally:
            observability.set_listener("bad", None)
        self.assertTrue(any(e["kind"] == "end" for e in self.got))

    def test_without_listener_same_as_before(self):
        observability.set_listener("test", None)
        saved = dict(observability._LISTENERS)          # 다른 시험이 붙여 둔 리스너도 잠시 뗀다
        observability._LISTENERS.clear()
        try:
            with observability.node_step("planner", as_type="agent") as obs:
                self.assertIs(obs, observability.NOOP) if observability.client() is None else None
        finally:
            observability._LISTENERS.update(saved)
        self.assertEqual(self.got, [])


class DbWatchTest(unittest.TestCase):
    def setUp(self):
        self.svc = sim_service()
        self.watch = db_watch.attach(self.svc)
        self.board = self.svc.board

    def lost(self, text="검정 카드지갑 잃어버렸어요, 해운대역"):
        r = self.svc.sim.lost(text, {"visit": "kiosk", "name_masked": "변*원", "id_no_masked": ID_MASKED})
        for _ in range(5):
            if not r.get("pending_id"):
                break
            r = self.svc.sim.answer(r["pending_id"], "모름")
        return r

    def test_attach_once(self):
        self.assertIs(db_watch.attach(self.svc), self.watch)
        self.assertEqual(self.watch.source, "memory")

    def test_full_round_events(self):
        start = self.board.last_seq
        rec = self.svc.create_item({"machine_id": "KIOSK-A", "place_text": "해운대역 승강장",
                                    "finder": {"name": "김습득", "phone": PHONE}})
        iid = rec["item_id"]
        evs = db_events(self.board, start)
        self.assertEqual([(e["db"]["table"], e["db"]["op"]) for e in evs],
                         [("item", "INSERT"), ("finder_contact", "INSERT"), ("item_status_log", "INSERT")])
        self.assertEqual(evs[0]["db"]["key"], iid)
        self.assertEqual(evs[0]["db"]["label"], "습득물")
        cols = {c["name"]: c for c in evs[0]["db"]["cols"]}
        self.assertEqual(cols["place_text"]["value"], "해운대역 승강장")
        self.assertEqual(cols["place_text"]["label"], "발견 장소")
        self.assertTrue(all(c["hidden"] for c in evs[1]["db"]["cols"] if c["name"] in ("name", "phone")))

        mark = self.board.last_seq
        self.svc.intake.set_features(iid, {"category": "지갑", "color": "검정", "mark": "별스티커비밀", "visible_text": "비밀글자"})
        ev = db_events(self.board, mark)[0]["db"]
        self.assertEqual((ev["table"], ev["op"]), ("item", "UPDATE"))
        cols = {c["name"]: c for c in ev["cols"]}
        self.assertEqual(cols["category"]["value"], "지갑")
        self.assertTrue(cols["private_features"]["hidden"])
        self.assertIn("2개", cols["private_features"]["value"])          # 몇 개 저장됐는지만

        blob = json.dumps(db_events(self.board, start), ensure_ascii=False)
        for secret in ("김습득", PHONE, "별스티커비밀", "비밀글자"):          # 연락처·비공개 특징 값은 사건 어디에도 없다
            self.assertNotIn(secret, blob)

    def test_lost_claim_and_kiosk_return(self):
        d = self.svc.sim.found("해운대역 승강장에서 검정 카드지갑 주웠어요")
        self.assertTrue(self.svc.sim.wait_idle(20))
        mark = self.board.last_seq
        r = self.lost()
        self.assertTrue(r.get("claim_id"), r)
        self.svc.sim.wait_idle(20)
        evs = db_events(self.board, mark)
        ops = [(e["db"]["table"], e["db"]["op"]) for e in evs]
        self.assertIn(("item", "SELECT"), ops)                                   # 후보 검색(읽기)
        self.assertLess(ops.index(("item", "SELECT")), ops.index(("claim", "INSERT")))
        for t in ("quiz_attempt", "reservation"):
            self.assertIn((t, "INSERT"), ops)
        claim = next(e["db"] for e in evs if e["db"]["table"] == "claim" and e["db"]["op"] == "INSERT")
        cols = {c["name"]: c for c in claim["cols"]}
        self.assertEqual(cols["name_masked"]["value"], "변*원")
        self.assertTrue(cols["id_no_masked"]["hidden"])
        self.assertNotIn(ID_MASKED, json.dumps(evs, ensure_ascii=False))          # 가린 신분 번호도 화면으로 내보내지 않음

        # 화면이 자주 부르는 조회(문맥 밖)는 사건을 남기지 않는다
        mark = self.board.last_seq
        for _ in range(3):
            self.svc.get_claim(r["claim_id"])
            self.svc.storage_status()
        self.assertEqual(db_events(self.board, mark), [])

        # 키오스크 회수: 찾기 요청을 읽고(SELECT) → 상태가 바뀌고 → 반환 기록이 저장된다
        out = self.svc.kiosk_return({"machine_id": "CENTER", "claim_id": r["claim_id"], "id_no_masked": ID_MASKED})
        self.assertEqual(out["decision"], "returned", out)
        self.svc.sim.wait_idle(20)
        evs = db_events(self.board, mark)
        ops = [(e["db"]["table"], e["db"]["op"]) for e in evs]
        self.assertEqual(ops[0], ("claim", "SELECT"))
        self.assertEqual(evs[0]["db"]["by"], "본센터 키오스크 회수")
        for want in (("item", "UPDATE"), ("item_status_log", "INSERT"), ("reservation", "UPDATE"),
                     ("return_case", "INSERT"), ("return_step", "INSERT")):
            self.assertIn(want, ops)
        self.assertNotIn(ID_MASKED, json.dumps(evs, ensure_ascii=False))
        self.assertEqual(d["item_id"], out["matched_object"])

    def test_same_status_rewrite_is_skipped_and_select_is_quiet(self):
        d = self.svc.sim.found("해운대역 승강장에서 검정 카드지갑 주웠어요")
        self.svc.sim.wait_idle(20)
        logs = [e["db"] for e in db_events(self.board) if e["db"]["table"] == "item_status_log" and e["db"]["key"] == d["item_id"]]
        moves = [(next(c["value"] for c in x["cols"] if c["name"] == "from_status"),
                  next(c["value"] for c in x["cols"] if c["name"] == "to_status")) for x in logs]
        self.assertTrue(all(a != b for a, b in moves), moves)                     # 같은 상태 → 같은 상태 기록은 없다
        mark = self.board.last_seq
        for _ in range(4):
            self.svc.sim.candidates({"category": "지갑"}, None)
        self.assertEqual(len(db_events(self.board, mark)), 1)                     # 같은 읽기는 잠깐 동안 한 번만

    def test_reset_is_one_line(self):
        mark = self.board.last_seq
        self.svc.sim.reset()
        evs = db_events(self.board, mark)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["db"]["by"], "가상 세계 초기화")

    def test_store_error_passes_through_without_event(self):
        from agents.intake import IntakeError
        mark = self.board.last_seq
        with self.assertRaises(IntakeError):
            self.svc.intake.create({"machine_id": "KIOSK-A", "place_id": 999999, "place_text": "x", "photo_path": None, "finder": None})
        self.assertEqual(db_events(self.board, mark), [])

    def test_service_without_board_is_untouched(self):
        from agents.service import TowerService, demo_backend_factory

        class Rep:
            def send(self, *a, **k):
                return True
        svc = TowerService(demo_backend_factory(), Rep())
        before = svc.intake.create
        self.assertIsNone(db_watch.attach(svc))
        self.assertEqual(svc.intake.create, before)


class ApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        self.svc = sim_service()
        self.c = TestClient(build_app(self.svc))

    def tearDown(self):
        observability.set_listener("live-board", None)

    def test_state_detail_and_pages(self):
        r = self.c.post("/sim/found", json={"text": "해운대역 승강장에서 검정 카드지갑 주웠어요"})
        self.assertEqual(r.status_code, 200)
        self.svc.sim.wait_idle(20)
        plain = self.c.get("/api/admin/live/state?after=0").json()
        self.assertNotIn("db_source", plain)
        self.assertFalse({e["channel"] for e in plain["events"]} & {"db", "trace"})
        full = self.c.get("/api/admin/live/state?after=0&detail=1").json()
        self.assertEqual(full["db_source"], "memory")
        self.assertIn("langfuse", full)
        tables = {e["db"]["table"] for e in full["events"] if e["channel"] == "db"}
        self.assertTrue({"item", "item_status_log", "storage_assignment"} <= tables, tables)

        page = self.c.get("/showcase")
        self.assertEqual(page.status_code, 200)
        self.assertIn("detail=1", page.text)
        for old, new in (("/intake", "/kiosk"), ("/storage-desk", "/storage")):
            moved = self.c.get(old)
            self.assertEqual(moved.status_code, 200)
            self.assertIn(f'location.replace("{new}" + location.search', moved.text)
        home = self.c.get("/").text
        self.assertIn('href="/showcase"', home)
        self.assertLess(home.index('href="/showcase"'), home.index("<details>"))      # 통합 시연은 위쪽 발표 목록에
        self.assertGreater(home.index('href="/live"'), home.index("<details>"))       # 시험·개발용은 접힌 칸에

    def test_chat_question_draws_agent_trace(self):
        mark = self.svc.board.last_seq
        r = self.c.post("/chat/questions", json={"question": "검정 지갑 잃어버렸어요", "session_id": "s-showcase"})
        self.assertEqual(r.status_code, 200)
        evs = self.c.get(f"/api/admin/live/state?after={mark}&detail=1").json()["events"]
        trace = [e["trace"] for e in evs if e["channel"] == "trace"]
        names = [t["name"] for t in trace if t["kind"] == "end"]
        for n in ("coordinator", "planner", "supervisor", "item_search", "lost-found-chatbot"):
            self.assertIn(n, names)
        self.assertEqual(trace[0]["kind"], "trace_start")
        self.assertEqual(trace[-1]["kind"], "trace_end")
        reads = [e["db"] for e in evs if e["channel"] == "db"]
        self.assertTrue(any(d["op"] == "SELECT" and d["by"] == "챗봇 item_search" for d in reads))


class PageContractTest(unittest.TestCase):
    def test_showcase_page(self):
        html = (ROOT / "web" / "showcase" / "index.html").read_text(encoding="utf-8")
        for needle in ("/api/admin/live/state?after=${seq}&detail=1", "/kiosk?machine=${machine}", '"/kiosk?machine=CENTER"',
                       '$("fLost").src = "/phone"', '$("full").src = "/live"', 'getElementById("tabRet")', "/ui/theme.css",
                       "data-theme-slot", "prefers-reduced-motion"):
            self.assertIn(needle, html)
        self.assertNotIn("innerHTML = e.", html)                # 사건 글자는 esc() 를 거쳐 넣는다
        self.assertIsNone(re.search(r"\.(body|note|value|text)\}<", html))

    def test_removed_pages_and_admin_tab(self):
        self.assertFalse((ROOT / "web" / "lost-finder").exists())
        self.assertFalse((ROOT / "web" / "archive").exists())
        admin = (ROOT / "web" / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn("storage: '/storage'}", admin)


if __name__ == "__main__":
    unittest.main()
