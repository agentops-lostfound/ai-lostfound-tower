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
                with observability.node_step("planner", as_type="agent", input={"question": "립밤"}) as obs:
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

    def lost(self, text="검정 립밤 잃어버렸어요, 중앙역"):
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
        rec = self.svc.create_item({"machine_id": "KIOSK-A", "place_text": "중앙역 승강장",
                                    "finder": {"name": "김습득", "phone": PHONE}})
        iid = rec["item_id"]
        evs = db_events(self.board, start)
        self.assertEqual([(e["db"]["table"], e["db"]["op"]) for e in evs],
                         [("item", "INSERT"), ("finder_contact", "INSERT"), ("item_status_log", "INSERT")])
        self.assertEqual(evs[0]["db"]["key"], iid)
        self.assertEqual(evs[0]["db"]["label"], "습득물")
        cols = {c["name"]: c for c in evs[0]["db"]["cols"]}
        self.assertEqual(cols["place_text"]["value"], "중앙역 승강장")
        self.assertEqual(cols["place_text"]["label"], "발견 장소")
        self.assertTrue(all(c["hidden"] for c in evs[1]["db"]["cols"] if c["name"] in ("name", "phone")))

        mark = self.board.last_seq
        self.svc.intake.set_features(iid, {"category": "립밤", "color": "검정", "mark": "별스티커비밀", "visible_text": "비밀글자"})
        ev = db_events(self.board, mark)[0]["db"]
        self.assertEqual((ev["table"], ev["op"]), ("item", "UPDATE"))
        cols = {c["name"]: c for c in ev["cols"]}
        self.assertEqual(cols["category"]["value"], "립밤")
        self.assertTrue(cols["private_features"]["hidden"])
        self.assertIn("2개", cols["private_features"]["value"])          # 몇 개 저장됐는지만

        blob = json.dumps(db_events(self.board, start), ensure_ascii=False)
        for secret in ("김습득", PHONE, "별스티커비밀", "비밀글자"):          # 연락처·비공개 특징 값은 사건 어디에도 없다
            self.assertNotIn(secret, blob)

    def test_lost_claim_and_kiosk_return(self):
        d = self.svc.sim.found("중앙역 승강장에서 검정 립밤 주웠어요")
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
        self.assertIn(("storage_assignment", "DELETE"), ops)                      # 11/11(021) 제출보관함에 놓이면 로봇 칸이 바로 빔
        rel = next(e["db"] for e in evs if e["db"]["table"] == "storage_assignment")
        self.assertEqual((rel["key"], rel["by"]), (out["matched_object"], "DB 트리거"))
        self.assertIn("인계 대기", rel["note"])

        # 11/11 무인 인계: [물건 받았어요] → 인계 완료 → 보관 칸이 저절로 빔(트리거) 사건이 남는다(화면 item 카드 slot_id '비움')
        mark = self.board.last_seq
        self.svc.sim.kiosk_handover({"machine_id": "CENTER", "claim_id": r["claim_id"], "id_no_masked": ID_MASKED})
        evs = db_events(self.board, mark)
        ops = [(e["db"]["table"], e["db"]["op"]) for e in evs]
        self.assertIn(("item", "UPDATE"), ops)
        self.assertNotIn(("storage_assignment", "DELETE"), ops)                   # 칸은 제출보관함에 놓일 때(인계 대기) 이미 비었음

    def test_same_status_rewrite_is_skipped_and_select_is_quiet(self):
        d = self.svc.sim.found("중앙역 승강장에서 검정 립밤 주웠어요")
        self.svc.sim.wait_idle(20)
        logs = [e["db"] for e in db_events(self.board) if e["db"]["table"] == "item_status_log" and e["db"]["key"] == d["item_id"]]
        moves = [(next(c["value"] for c in x["cols"] if c["name"] == "from_status"),
                  next(c["value"] for c in x["cols"] if c["name"] == "to_status")) for x in logs]
        self.assertTrue(all(a != b for a, b in moves), moves)                     # 같은 상태 → 같은 상태 기록은 없다
        mark = self.board.last_seq
        for _ in range(4):
            self.svc.sim.candidates({"category": "립밤"}, None)
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
        r = self.c.post("/sim/found", json={"text": "중앙역 승강장에서 검정 립밤 주웠어요"})
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
        r = self.c.post("/chat/questions", json={"question": "검정 립밤 잃어버렸어요", "session_id": "s-showcase"})
        self.assertEqual(r.status_code, 200)
        evs = self.c.get(f"/api/admin/live/state?after={mark}&detail=1").json()["events"]
        trace = [e["trace"] for e in evs if e["channel"] == "trace"]
        names = [t["name"] for t in trace if t["kind"] == "end"]
        for n in ("coordinator", "planner", "supervisor", "item_search", "reporter", "lost-found-chatbot"):
            self.assertIn(n, names)
        # 11/10 reporter 도 기록에 남는다: 일꾼 → supervisor → reporter → supervisor(끝) → 질문 전체 끝 순서
        self.assertEqual(names[-4:], ["supervisor", "reporter", "supervisor", "lost-found-chatbot"])
        rep = next(t for t in trace if t["kind"] == "end" and t["name"] == "reporter")
        self.assertIn("answer", rep["output"])
        self.assertEqual(trace[0]["kind"], "trace_start")
        self.assertEqual(trace[-1]["kind"], "trace_end")
        reads = [e["db"] for e in evs if e["channel"] == "db"]
        self.assertTrue(any(d["op"] == "SELECT" and d["by"] == "챗봇 item_search" for d in reads))


class PageContractTest(unittest.TestCase):
    def test_showcase_page(self):
        html = (ROOT / "web" / "showcase" / "index.html").read_text(encoding="utf-8")
        for needle in ("/api/admin/live/state?after=${seq}&detail=1", "/kiosk?machine=${machine}", '"/kiosk?machine=CENTER&tab=ret&demo=1&in=showcase"',
                       '$("fLost").src = "/phone"', '$("full").src = "/live?embed=1"', "/ui/theme.css",
                       "data-theme-slot", "prefers-reduced-motion"):
            self.assertIn(needle, html)
        # 11/10 에이전트 그림은 일이 생긴 쪽으로 자동 전환(사용자가 한 번 고르면 영영 멈추던 옛 방식 'pinned' 는 없앰),
        # 재생은 밀린 시간에 맞춰 빨라지고, reporter 는 실제 단계 기록으로 그린다
        for needle in ("function follow(name)", "CHAT_KEEP_MS", "USER_HOLD_MS", "late > 900", "chatReported", "scrollbar-width:none"):
            self.assertIn(needle, html)
        self.assertNotIn("pinned", html)
        # 11/10 챗봇 답과 그림이 같은 때에 끝나게: 끝난 질문의 남은 단계는 곧바로 재생(_rush), 챗봇 창의 "질문 보냄" 알림을 받는다
        for needle in ("_rush", 'e.data.source !== "lostfound-chat"', "e.origin !== location.origin"):
            self.assertIn(needle, html)
        self.assertNotIn("|| stories[0]", html)                 # 다른 종류의 건을 진행 막대에 대신 보여 주지 않는다
        self.assertNotIn("innerHTML = e.", html)                # 사건 글자는 esc() 를 거쳐 넣는다
        self.assertIsNone(re.search(r"\.(body|note|value|text)\}<", html))

    def test_chat_widget_shows_answer_after_full_bar(self):
        js = (ROOT / "web" / "chat-widget" / "widget.js").read_text(encoding="utf-8")
        self.assertIn("progress.complete(resolve)", js)          # 막대가 100% 가 된 뒤에 답을 붙인다
        self.assertNotIn("progress.finish(", js)                 # 답을 먼저 보이고 막대가 따라가던 옛 방식
        self.assertLess(js.index("progress.complete(resolve)"), js.index('var m = line("bot", answerText);'))
        ask = js[js.index("window.top.postMessage"):js.index("window.top.postMessage") + 120]
        self.assertIn('phase: "ask"', ask)
        self.assertIn("location.origin", ask)                    # 같은 주소의 바깥 화면에만 알린다
        self.assertNotIn("question", ask)                        # 질문 내용은 보내지 않는다

    def test_removed_pages_and_admin_tab(self):
        for gone in ("lost-finder", "archive", "intake"):          # 11/10 정리한 옛 화면 폴더(주소 /intake 는 /kiosk 로 넘김)
            self.assertFalse((ROOT / "web" / gone).exists(), gone)
        admin = (ROOT / "web" / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn("storage: '/storage'}", admin)



class LiveEmbedTest(unittest.TestCase):
    def test_live_embed_mode_fits_one_screen(self):
        """11/11 발표 화면 ④: /live?embed=1 은 제목·연결 칩을 빼고 작업대 그림 높이를 화면에 맞춘다"""
        html = (ROOT / "web" / "live" / "index.html").read_text(encoding="utf-8")
        self.assertIn('get("embed") === "1") document.documentElement.classList.add("embed")', html)
        self.assertIn("html.embed #bench{max-height:calc(100vh - 150px)", html)
        self.assertIn("html.embed header h1,html.embed header .chip.conn{display:none}", html)


class UiFixes1111Test(unittest.TestCase):
    """11/11 사용자 요청: 붙여넣기 · 사진 크게 보기 · 색 고르기 정리 · 키오스크 분실 접수 · ① 탭 역 바꾸기"""
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_paste_into_vk_fields(self):
        js = self.read("web/ui/vkeyboard.js")
        self.assertIn('doc.addEventListener("paste"', js)                 # readonly 칸이라 브라우저가 막던 Ctrl+V
        self.assertIn('if (st.kind === "num") text = text.replace(/[^0-9-]/g, "")', js)

    def test_photo_lightbox(self):
        html = self.read("web/showcase/index.html")
        self.assertIn('<div class="lightbox" id="lightbox" hidden role="dialog"', html)
        self.assertIn('closest(".dbtable img.ph, .vhead img")', html)

    def test_lost_colors_grouped_and_kiosk_embed(self):
        html = self.read("web/lost/index.html")
        self.assertIn("'립밤': ['빨강', '파랑']", html)
        self.assertIn("다른 색 ${rest.length}개 ▾", html)
        self.assertIn('get("embed") === "kiosk") document.documentElement.classList.add("embed-kiosk")', html)
        kiosk = self.read("web/kiosk/index.html")
        self.assertIn('<iframe id="lostFrame"', kiosk)
        self.assertIn("f.src = '/lost?embed=kiosk'", kiosk)
        self.assertNotIn("아직 저장은 안 돼요(준비 중)", kiosk)
        self.assertIn("Q.get('camsrc') || Q.get('machine')", kiosk)

    def test_contact_send_disabled_when_empty(self):
        """11/11 연락처 화면: 이름·전화번호가 모두 비면 [보내기] 꺼짐(건너뛰기는 그대로)"""
        html = self.read("web/kiosk/index.html")
        self.assertIn('<button id="send" disabled>보내기</button>', html)
        self.assertIn("function contactCheck() { $('#send').disabled = sending || !($('#cname').value.trim() || $('#cphone').value.trim()); }", html)
        self.assertIn("$('#cname').oninput = contactCheck;", html)

    def test_found_tab_swaps_station(self):
        html = self.read("web/showcase/index.html")
        self.assertIn('const FOUND_STN = {"KIOSK-A": "중앙역", "KIOSK-C": "초량역"};', html)
        self.assertIn('if (sc === "found" && scene === "found") swapFound();', html)

    def test_two_views_three_tabs_1112(self):
        """11/12 발표 검토: 탭은 습득/분실/회수 3개, 화면은 키오스크+DB·에이전트(간단히) ⇄ 키오스크 크게(단추 하나),
        로봇 작업대는 작은 단추, 키오스크 탭 ⇄ 발표 장면 맞춤(postMessage, 같은 출처만)"""
        html = self.read("web/showcase/index.html")
        self.assertEqual(html.count('role="tab" data-scene='), 3)
        self.assertNotIn('data-scene="robot"', html)
        for needle in ('id="btnView"', 'id="btnRobot"', 'id="btnMore"', 'body.kview main > .panel{visibility:hidden;opacity:0}',
                       'document.body.classList.add("simple")', '"kiosk-set-tab"', 'd.type === "showcase-go"',
                       'stationret', 'lostweb', '&in=showcase'):
            self.assertIn(needle, html)
        k = self.read("web/kiosk/index.html")
        for needle in ('id="goWeb"', 'id="goCenter"', "IN_SHOWCASE", "e.origin !== location.origin", "tellShowcase('kiosk-tab'"):
            self.assertIn(needle, k)

    def test_robot_view_returns_to_kiosk_when_delivered_1113(self):
        """11/13 로봇 작업대를 보던 중 제출보관함 전달이 끝나면 스스로 키오스크([물건 받았어요] 화면)로 돌아옴 —
        이야기마다 바뀌는 순간에 한 번, 새로고침으로 처음 본 대기 상태는 건드리지 않음"""
        html = self.read("web/showcase/index.html")
        for needle in ("function backToKiosk()", "const now = handoverWait(st), before = waitSeen[st.story_id];",
                       "if (!now || before !== false || !robotOpen) return;", "else setRobot(false); }, 2500);",
                       "function renderSteps() {\n    backToKiosk();"):
            self.assertIn(needle, html)

    def test_stable_layout_1112(self):
        """11/12 오후: 장면·보기를 바꿔도 키오스크 자리·크기가 같게 — 칸 나눔은 그대로 두고 패널만 감춤, 설명 3줄·바로가기 칸 자리 고정,
        휴대폰 장면도 같은 왼쪽 칸 폭, 탭·보기 단추 폭 고정"""
        html = self.read("web/showcase/index.html")
        self.assertNotIn("body.kview main{grid-template-columns", html)
        self.assertIn("body.kview #steps,body.kview .cap{display:none}", html)   # 11/12 오후(2) 키오스크만 보기는 최대한 크게
        for needle in ("height:calc(1.45em * 3)", ".devgo{display:flex;gap:8px;justify-content:center;flex-wrap:nowrap;height:38px",
                       "const devw = Math.max(screenW + 20 + 54, pw + 22);", "height:44px;box-sizing:border-box",
                       ".scenes button[aria-selected=\"true\"] .swap{visibility:visible}", "#btnView{min-width:12.5em}"):
            self.assertIn(needle, html)
        # 11/12 오후: 키오스크는 늘 가운데(왼쪽 DB · 가운데 기기 · 오른쪽 에이전트)
        self.assertIn("grid-template-columns:minmax(0,1fr) var(--devw,400px) minmax(0,1fr)", html)
        self.assertIn("#deviceCol{order:2} #panelDb{order:1} #panelAgent{order:3}", html)
        vk = self.read("web/ui/vkeyboard.js")
        self.assertIn("b.tabIndex = -1;", vk)                                   # 화면 글쇠는 Tab 순서 밖
        self.assertIn("else if (st.el && !kb.contains(el)) hide();", vk)        # Tab 으로 칸을 벗어나면 키보드·여백 닫기

if __name__ == "__main__":
    unittest.main()


class SimReviewFixTest(unittest.TestCase):
    """11/10 사람 조작 점검에서 고친 것: ① 쌓인 기록이 200개를 넘으면 나머지를 건너뛰던 문제 ② 초기화 전 연습 기록이 새로 연 발표 화면에 섞이던 문제"""

    def test_since_pages_and_epoch(self):
        from agents.live import LiveBoard
        b = LiveBoard()
        for i in range(250):
            b.db("item", "INSERT", f"A-{i}")
        first = b.since(0, detail=True)
        self.assertEqual(len(first), 200)
        rest = b.since(first[-1]["seq"], detail=True)
        self.assertEqual(len(rest), 50)                                     # 받은 데부터 이어 받으면 빠짐이 없다
        b.mark_epoch()
        b.db("claim", "INSERT", "C-1")
        fresh = b.since(0, detail=True)
        self.assertEqual([e["db"]["key"] for e in fresh], ["C-1"])          # 초기화 뒤 것만
        self.assertEqual(len(b.since(0)), 0)                                # 이야기 사건(/live)은 전과 같음(db 사건 없음)

    def test_state_more_flag_keeps_seq_at_last_returned(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        svc = sim_service()
        try:
            c = TestClient(build_app(svc))
            for i in range(230):
                svc.board.db("item", "SELECT", f"A-{i}")
            d = c.get("/api/admin/live/state?after=0&detail=1").json()
            self.assertTrue(d["more"])
            self.assertEqual(d["seq"], d["events"][-1]["seq"])
            d2 = c.get(f"/api/admin/live/state?after={d['seq']}&detail=1").json()
            self.assertFalse(d2["more"])
            self.assertEqual(d2["seq"], svc.board.last_seq)
            c.post("/sim/reset", json={})
            d3 = c.get("/api/admin/live/state?after=0&detail=1").json()
            self.assertFalse(any(e.get("db", {}).get("key", "").startswith("A-1") and e["db"]["op"] == "SELECT"
                                 for e in d3["events"] if e["channel"] == "db"))
        finally:
            observability.set_listener("live-board", None)
