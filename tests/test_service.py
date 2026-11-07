"""관제탑 서비스·API 시험 — FastAPI 없이 규칙(agents/service.py)과 경로 등록(agents/api.py)을 확인."""
import os
import sys
import threading
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED  # noqa: E402
from agents.records import MemoryRecorder, to_record  # noqa: E402
from agents.service import (  # noqa: E402
    GATE_FIELDS, Conflict, NotFound, RequestError, TowerService, Unavailable, demo_backend_factory, parse_request,
)
from discord_ops.reporter import Reporter  # noqa: E402


def schema_text():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "center", "schema.sql"), encoding="utf-8") as f:
        return f.read()


def ok_payload(case="R1", item="A-W01", **over):
    p = {"case_id": case, "item_id": item, **{g: True for g in GATE_FIELDS}}
    p.update(over)
    return p


def service(**kw):
    return TowerService(demo_backend_factory(), Reporter(), **kw)


class ParseTest(unittest.TestCase):
    def test_ok(self):
        req = parse_request(ok_payload())
        self.assertEqual((req.case_id, req.item_id), ("R1", "A-W01"))
        self.assertTrue(req.staff_confirmed)

    def test_rejects(self):
        bad = [
            "문자열",
            ok_payload(name="홍길동"),                 # 개인정보 칸
            ok_payload(case="R 1"),                    # 공백
            ok_payload(case="R" * 33),                 # 너무 김
            ok_payload(item=""),
            ok_payload(consent="true"),                # 문자열 true
            ok_payload(consent=1),                     # 숫자
        ]
        for p in bad:
            with self.assertRaises(RequestError, msg=p):
                parse_request(p)

    def test_missing_gate(self):
        p = ok_payload()
        del p["staff_confirmed"]
        with self.assertRaises(RequestError):
            parse_request(p)


class ServiceTest(unittest.TestCase):
    def test_demo_return_and_record(self):
        svc = service()
        out = svc.start_return(ok_payload())
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertEqual(out["matched_object"], "W01")
        row = svc.get_case("R1")
        self.assertEqual(row["item_id"], "A-W01")
        self.assertTrue(row["steps"])
        self.assertEqual(svc.recent()[0]["case_id"], "R1")
        self.assertNotIn("steps", svc.recent()[0])

    def test_each_request_gets_fresh_backend(self):
        svc = service()
        for i in range(3):   # 가짜 부품의 집기 횟수가 다음 요청에 남으면 2번째부터 실패함
            self.assertEqual(svc.start_return(ok_payload(case=f"R{i}"))["decision"], DECISION_RETURNED)

    def test_duplicate_case_never_runs_twice(self):
        calls = []

        def flow(req, be, rep, reviewer=None):
            calls.append(req.case_id)
            from agents.supervisor import run_return
            return run_return(req, be, rep, reviewer)
        svc = service(flow=flow)
        svc.start_return(ok_payload())
        with self.assertRaises(Conflict) as cm:
            svc.start_return(ok_payload())
        self.assertEqual(cm.exception.kind, "duplicate")
        self.assertEqual(calls, ["R1"])

    def test_busy_while_running(self):
        started, release = threading.Event(), threading.Event()

        def slow_flow(req, be, rep, reviewer=None):
            started.set()
            release.wait(5)
            from agents.supervisor import run_return
            return run_return(req, be, rep, reviewer)
        svc = service(flow=slow_flow)
        t = threading.Thread(target=svc.start_return, args=(ok_payload(case="R1"),))
        t.start()
        started.wait(5)
        self.assertTrue(svc.health()["busy"])
        with self.assertRaises(Conflict) as cm:
            svc.start_return(ok_payload(case="R2"))
        self.assertEqual(cm.exception.kind, "busy")
        release.set()
        t.join(5)
        self.assertFalse(svc.health()["busy"])
        self.assertIsNone(svc.get_case("R2"))   # 거절된 요청은 기록도 없음

    def test_gate_rejected_and_unknown_item(self):
        svc = service()
        self.assertEqual(svc.start_return(ok_payload(case="G1", quiz_passed=False))["decision"], DECISION_REJECTED)
        self.assertEqual(svc.start_return(ok_payload(case="G2", item="A-ZZZ"))["decision"], DECISION_STAFF)

    def test_part_exception_stops_robot_and_records(self):
        stops = []

        class Exploding:
            def __getattr__(self, name):
                if name == "robot_stop":
                    return lambda: (stops.append(1), {"ok": True})[1]
                raise RuntimeError("부품이 예외를 던짐")
        rep = Reporter()
        svc = TowerService(lambda: Exploding(), rep)
        out = svc.start_return(ok_payload(case="X1"))
        self.assertEqual(out["decision"], DECISION_STOPPED)
        self.assertIn("흐름 오류", out["reason"])
        self.assertEqual(stops, [1])
        self.assertTrue(any(m["channel"] == "alert" for m in rep.messages))
        self.assertIsNotNone(svc.get_case("X1"))
        self.assertFalse(svc.health()["busy"])   # 예외가 나도 잠금이 풀림

    def test_get_case_validates(self):
        with self.assertRaises(RequestError):
            service().get_case("../etc")

    def test_health_reports_sources(self):
        h = service().health()
        self.assertTrue(h["ok"])
        self.assertFalse(h["send"])
        self.assertEqual(set(h["sources"].values()), {"가짜"})


class TeamChannelTest(unittest.TestCase):
    """팀 대화 채널: 반환 1건당 결과 한 줄, 개인정보 없음, 웹후크 없으면 시험 채널로 대신 보내지 않음"""

    def test_one_summary_per_return(self):
        rep = Reporter()
        svc = TowerService(demo_backend_factory(), rep)
        svc.start_return(ok_payload(case="T1"))
        svc.start_return(ok_payload(case="T2", quiz_passed=False))
        team = [m for m in rep.messages if m["channel"] == "team"]
        self.assertEqual(len(team), 2)
        self.assertIn("[T1] 물건 A-W01 · ✅ 반환 완료", team[0]["title"])
        self.assertIn("⛔ 반환 안 함", team[1]["title"])

    def test_no_summary_for_refused_requests(self):
        rep = Reporter()
        svc = TowerService(demo_backend_factory(), rep)
        svc.start_return(ok_payload(case="T1"))
        with self.assertRaises(Conflict):
            svc.start_return(ok_payload(case="T1"))
        self.assertEqual(len([m for m in rep.messages if m["channel"] == "team"]), 1)

    def test_team_never_falls_back_to_test_channel(self):
        from discord_ops import reporter as rmod
        sent = []
        import tools.notify as nmod
        import tools.envfile as emod
        orig_notify, orig_env, orig_load = nmod.notify, dict(os.environ), emod.load_env
        try:
            emod.load_env = lambda *a, **k: None   # PC 의 .env(팀 웹후크 있음)를 다시 읽어 시험이 흔들리지 않게
            nmod.notify = lambda title, body="", env_key="": sent.append(env_key) or True
            os.environ.pop("DISCORD_WEBHOOK_TEAM", None)
            os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/x/y"
            self.assertFalse(rmod._post("team", "t", "b"))
            self.assertEqual(sent, [])
            os.environ.pop("DISCORD_WEBHOOK_ALERT", None)
            rmod._post("alert", "t", "b")                             # 다른 채널은 기존처럼 공용 웹후크로 대체
            self.assertEqual(sent, ["DISCORD_WEBHOOK_URL"])
        finally:
            nmod.notify = orig_notify
            emod.load_env = orig_load
            os.environ.clear()
            os.environ.update(orig_env)


class RecordTest(unittest.TestCase):
    def test_record_has_no_pii_columns(self):
        row = to_record("A-1", {"case_id": "R1", "decision": "returned", "reason": "반환 완료", "steps": ["a"]})
        self.assertEqual(set(row), {"case_id", "item_id", "claim_id", "decision", "reason", "approved", "matched_object",
                                    "seconds", "created_at", "steps"})

    def test_memory_recorder_refuses_overwrite(self):
        r = MemoryRecorder()
        r.save("A-1", {"case_id": "R1", "decision": "returned", "reason": ""})
        with self.assertRaises(KeyError):
            r.save("A-1", {"case_id": "R1", "decision": "returned", "reason": ""})

    def test_schema_matches_record_columns(self):
        sql = schema_text()
        block = sql[sql.index("CREATE TABLE IF NOT EXISTS return_case"):sql.index("CREATE TABLE IF NOT EXISTS return_step")]
        for col in ("case_id", "item_id", "decision", "reason", "approved", "matched_object", "seconds", "created_at"):
            self.assertIn(col, block)

    def test_schema_checks_match_contracts(self):
        """DB 의 CHECK 목록이 contracts.py 상수와 같아야 한다(한쪽만 바꾸는 실수 방지)"""
        import re
        from agents.contracts import DECISIONS, ITEM_STATUS
        sql = schema_text()
        status = re.search(r"CHECK \(status IN \((.*?)\)\)", sql, re.S).group(1)
        self.assertEqual(re.findall(r"'([^']+)'", status), ITEM_STATUS)
        decision = re.search(r"CHECK \(decision IN \((.*?)\)\)", sql, re.S).group(1)
        self.assertEqual(re.findall(r"'([^']+)'", decision), DECISIONS)

    def test_schema_has_no_resident_number_column(self):
        sql = schema_text().lower()
        for word in ("resident", "rrn", "jumin"):
            self.assertNotIn(word, sql)


class ApiRoutesTest(unittest.TestCase):
    """가짜 fastapi 로 경로 등록과 오류 코드 변환만 확인(진짜 실행은 시연 PC에서)."""

    def setUp(self):
        self.routes = {}
        routes = self.routes

        class HTTPException(Exception):
            def __init__(self, status_code, detail=None):
                self.status_code, self.detail = status_code, detail

        class FakeFastAPI:
            def __init__(self, **kw):
                self.kw = kw

            def _reg(self, method, path):
                def deco(fn):
                    routes[(method, path)] = fn
                    return fn
                return deco

            def get(self, path, **kw):
                return self._reg("GET", path)

            def post(self, path, **kw):
                return self._reg("POST", path)

        fake = types.ModuleType("fastapi")
        fake.FastAPI, fake.HTTPException, fake.Body = FakeFastAPI, HTTPException, (lambda *a, **k: None)
        fake.Header = lambda *a, **k: None     # 11/5 챗봇 위젯 주소(agents/chat_api.py)
        fake.Depends = lambda *a, **k: None    # 11/5 관리자 로그인 문지기(agents/admin_auth.py)
        fake.Request = fake.Response = object
        self.HTTPException = HTTPException
        sys.modules["fastapi"] = fake
        responses = types.ModuleType("fastapi.responses")

        class HTMLResponse:
            def __init__(self, content):
                self.body = content.encode("utf-8")
        responses.HTMLResponse = HTMLResponse
        responses.FileResponse = lambda path, **k: types.SimpleNamespace(path=path, **k)
        sys.modules["fastapi.responses"] = responses

    def tearDown(self):
        sys.modules.pop("fastapi", None)
        sys.modules.pop("fastapi.responses", None)

    def test_routes_and_status_codes(self):
        from agents import api
        api.build_app(service())
        r = self.routes
        new_api = [("GET", "/"), ("GET", "/admin")] + [("GET", p) for p in ("/api/admin/claims/{claim_id}", "/api/admin/live/state", "/api/admin/me", "/api/admin/returns",
                                        "/api/admin/returns/{case_id}", "/api/admin/robot/state", "/api/kiosk/places",
                                        "/api/admin/storage", "/api/admin/storage/export", "/api/admin/storage/checks",
                                        "/api/admin/handovers", "/api/admin/returns/{case_id}/secret", "/api/admin/items/{item_id}/photo", "/api/admin/intake/pending-photos",
                                        "/api/admin/storage/arrivals", "/storage-desk", "/storage")] + \
                  [("POST", p) for p in ("/api/admin/login", "/api/admin/logout", "/api/admin/returns",
                                         "/api/admin/returns/{case_id}/handover", "/api/admin/returns/{case_id}/hold",
                                         "/api/admin/robot/home", "/api/kiosk/claims", "/api/kiosk/items",
                                         "/api/kiosk/items/{item_id}/features", "/api/kiosk/returns", "/api/lost/claims", "/api/robot/stop",
                                         "/api/admin/storage/assign", "/api/admin/storage/release",   # 11/6 보관함 정답지
                                         "/api/admin/storage/slots/{slot_id}/pose", "/api/admin/storage/checks",
                                         "/api/admin/returns/{case_id}/verify", "/api/admin/returns/{case_id}/restock",
                                         "/api/admin/storage/arrivals/{item_id}/place")]   # 11/6 교차 검증   # 11/5 /api/ 주소 체계
        self.assertEqual(sorted(r), sorted(new_api + [("GET", "/chat-widget/demo"), ("GET", "/chat-widget/widget.js"), ("GET", "/chat/health"), ("GET", "/chat/metrics"), ("GET", "/chat/suggestions"), ("GET", "/claims/{claim_id}"), ("GET", "/health"), ("GET", "/intake"), ("GET", "/kiosk"), ("GET", "/live"), ("GET", "/live/so101_shape.js"), ("GET", "/live/state"), ("GET", "/lost"), ("GET", "/places"),
                                     ("GET", "/returns"), ("GET", "/returns/{case_id}"), ("GET", "/robot/state"), ("GET", "/sim/stories/{story_id}"), ("GET", "/staff"),
                                     ("GET", "/tools"), ("POST", "/chat/questions"), ("POST", "/claims"), ("POST", "/items"),
                                     ("POST", "/items/{item_id}/features"), ("POST", "/returns"),
                                     ("POST", "/returns/{case_id}/handover"), ("POST", "/returns/{case_id}/hold"),
                                     ("POST", "/robot/home"), ("POST", "/robot/stop"), ("POST", "/sim/found"),
                                 ("POST", "/sim/lost"), ("POST", "/sim/lost/{pending_id}/answer"), ("POST", "/sim/reset")]))
        self.assertEqual(r[("POST", "/returns")](ok_payload())["decision"], DECISION_RETURNED)
        for payload, code in ((ok_payload(), 409), (ok_payload(case="R2", phone="010"), 422)):
            with self.assertRaises(self.HTTPException) as cm:
                r[("POST", "/returns")](payload)
            self.assertEqual(cm.exception.status_code, code)
        with self.assertRaises(self.HTTPException) as cm:
            r[("GET", "/returns/{case_id}")]("NONE")
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(r[("GET", "/returns/{case_id}")]("R1")["case_id"], "R1")
        self.assertEqual(len(r[("GET", "/tools")]()), 12)
        self.assertIn("습득물", r[("GET", "/intake")]().body.decode("utf-8"))     # 11/4 등록기계 화면을 같은 주소에서
        kiosk = r[("GET", "/kiosk")]().body.decode("utf-8")                       # 11/4 습득자 키오스크: 관제탑 API 모양(machine_id·JSON)으로 부름
        self.assertIn("machine_id", kiosk)
        self.assertNotIn("FormData", kiosk)
        self.assertIn("분실물", r[("GET", "/lost")]().body.decode("utf-8"))
        # 11/4 인계: 바구니 전달(인계 대기) → 직원 확인 → 인계 완료, 두 번째는 409
        self.assertEqual(r[("POST", "/returns/{case_id}/handover")]("R1", {"staff_confirmed": True})["status"], "인계 완료")
        for args, code in ((("R1", {"staff_confirmed": True}), 409), (("NONE", {"staff_confirmed": True}), 404),
                           (("R1", {"staff_confirmed": False}), 422), (("R 1", {"staff_confirmed": True}), 422)):
            with self.assertRaises(self.HTTPException) as cm:
                r[("POST", "/returns/{case_id}/handover")](*args)
            self.assertEqual(cm.exception.status_code, code, args)
        with self.assertRaises(self.HTTPException) as cm:          # 이미 인계 완료 → 보류 불가
            r[("POST", "/returns/{case_id}/hold")]("R1", {"reason": "기타"})
        self.assertEqual(cm.exception.status_code, 409)

    def test_storage_routes(self):
        """11/6 보관함 정답지: 시연 부품(A-W01~, 본센터 보관)으로 넣기·충돌·자세·내보내기·오류 코드"""
        from agents import api
        api.build_app(service())
        r = self.routes
        self.assertEqual(r[("GET", "/api/admin/storage")]()["summary"]["shelf_slots"], 8)
        self.assertEqual(r[("POST", "/api/admin/storage/assign")]({"item_id": "A-W01", "slot_id": "R4-1"})["section"], "R4")
        for payload, code in (({"item_id": "A-W02", "slot_id": "R4-1"}, 409), ({"item_id": "A-W02", "slot_id": "R9-1"}, 404),
                              ({"item_id": "A-W02", "slot_id": "H-1"}, 422), ({"item_id": "A-W99", "slot_id": "R4-2"}, 404),
                              ([], 422)):
            with self.assertRaises(self.HTTPException) as cm:
                r[("POST", "/api/admin/storage/assign")](payload)
            self.assertEqual(cm.exception.status_code, code, payload)
        self.assertEqual(r[("POST", "/api/admin/storage/slots/{slot_id}/pose")]("R4-1", {"pose_name": "pose_1"})["pose_name"], "pose_1")
        out = r[("GET", "/api/admin/storage/export")]()
        self.assertEqual(out["inventory"], {"A-W01": {"section": "R4", "slot": "1"}})
        self.assertEqual(out["warnings"], [])
        check = {"section": "R4", "expected_count": 1, "detected_count": 1, "status": "count_match"}
        self.assertEqual(r[("POST", "/api/admin/storage/checks")](check)["id"], 1)
        self.assertEqual(len(r[("GET", "/api/admin/storage/checks")](5)), 1)
        self.assertEqual(r[("POST", "/api/admin/storage/release")]({"slot_id": "R4-1"})["item_id"], "A-W01")

    def test_cross_check_routes(self):
        """11/6 교차 검증 경로: 대기 목록·답 보기·검증·되돌림·사진 오류 코드"""
        from agents import api
        svc = service()
        api.build_app(svc)
        r = self.routes
        svc.start_return(ok_payload(case="Y1"))
        self.assertEqual(r[("GET", "/api/admin/handovers")](20)[0]["case_id"], "Y1")
        self.assertIn("mark", r[("GET", "/api/admin/returns/{case_id}/secret")]("Y1")["secret"])
        for args, code in ((("Y1", {"item_match": True}), 422), (("NONE", {"item_match": True, "id_match": True, "feature_match": True}), 404)):
            with self.assertRaises(self.HTTPException) as cm:
                r[("POST", "/api/admin/returns/{case_id}/verify")](*args)
            self.assertEqual(cm.exception.status_code, code)
        ok = {"item_match": True, "id_match": True, "feature_match": False}
        self.assertEqual(r[("POST", "/api/admin/returns/{case_id}/verify")]("Y1", ok)["result"], "반환 보류")
        self.assertEqual(r[("POST", "/api/admin/returns/{case_id}/restock")]("Y1", {"staff_confirmed": True})["status"], "본센터 보관")
        for item, code in (("A W01", 422), ("A-W01", 404)):
            with self.assertRaises(self.HTTPException) as cm:
                r[("GET", "/api/admin/items/{item_id}/photo")](item)
            self.assertEqual(cm.exception.status_code, code)

    def test_db_down_is_503(self):
        from agents import api
        from agents.records import PostgresRecorder

        def down(dsn):
            raise ConnectionError("DB 꺼짐")
        api.build_app(TowerService(demo_backend_factory(), Reporter(), recorder=PostgresRecorder("x", connect=down)))
        for call in (lambda: self.routes[("POST", "/returns")](ok_payload(case="Z1")),
                     lambda: self.routes[("GET", "/returns")](20),
                     lambda: self.routes[("GET", "/returns/{case_id}")]("Z1")):
            with self.assertRaises(self.HTTPException) as cm:
                call()
            self.assertEqual(cm.exception.status_code, 503)


class RobotButtonsTest(unittest.TestCase):
    """11/4: 직원 화면 정지(반환 중에도) · 원점 복귀(주변 확인 뒤, 진행 중이면 거부)."""

    def make(self):
        from agents.tools import MockBackend
        self.rep = Reporter()
        holder = {}

        def factory():
            be = MockBackend(bin_items=[{"object_id": "W01", "features": {"color": "검정"}, "center": [100, 200]}],
                             db={"A-W01": {"status": "본센터 보관", "features": {"color": "검정"}}})
            holder["be"] = be
            return be
        self.svc = TowerService(factory, self.rep)
        return holder

    def test_stop_during_return(self):
        self.rep = Reporter()
        svc = self.svc = TowerService(demo_backend_factory(), self.rep)
        base = svc.backend_factory

        def factory():
            be = base()
            mock = be.fallback
            real = mock.robot_approach

            def approach(mm, px):          # 사전 접근 도중 직원이 정지 버튼을 누름
                r = real(mm, px)
                svc.stop_robot()
                return r
            mock.robot_approach = approach
            self.mock = mock
            return be
        svc.backend_factory = factory
        out = svc.start_return(ok_payload(case="S1"))
        self.assertEqual(out["decision"], DECISION_STOPPED, out["reason"])
        self.assertIn("직원 정지 버튼", out["reason"])
        self.assertNotIn("robot_grasp", self.mock.calls)       # 정지 뒤 집기 명령은 부품에 가지 않음
        self.assertTrue(any(m["channel"] == "alert" and "직원 정지 버튼" in m["title"] for m in self.rep.messages))
        svc.backend_factory = base                              # 다음 반환은 정지 표시가 지워진 채로 시작
        self.assertEqual(svc.start_return(ok_payload(case="S2", item="A-W02"))["decision"], DECISION_RETURNED)

    def test_stop_when_idle_and_fail(self):
        holder = self.make()
        res = self.svc.stop_robot()
        self.assertEqual((res["ok"], res["running"]), (True, False))
        self.assertIn("robot_stop", holder["be"].calls)
        base = self.svc.backend_factory

        def bad():
            be = base()
            be.stop_ok = False
            return be
        self.svc.backend_factory = bad
        res = self.svc.stop_robot()
        self.assertFalse(res["ok"])
        self.assertTrue(any("정지 실패" in m["title"] for m in self.rep.messages if m["channel"] == "alert"))

    def test_home(self):
        holder = self.make()
        for body in ({}, {"staff_confirmed": False}, None):
            with self.assertRaises(RequestError):
                self.svc.robot_home(body)
        self.assertEqual(self.svc.robot_home({"staff_confirmed": True})["ok"], True)
        self.assertIn("robot_home", holder["be"].calls)
        self.svc._run_lock.acquire()           # 반환 진행 중
        try:
            with self.assertRaises(Conflict) as cm:
                self.svc.robot_home({"staff_confirmed": True})
            self.assertEqual(cm.exception.kind, "busy")
        finally:
            self.svc._run_lock.release()

    def test_home_fail_alerts(self):
        self.make()
        base = self.svc.backend_factory

        def bad():
            be = base()
            be.home_ok = False
            return be
        self.svc.backend_factory = bad
        self.assertFalse(self.svc.robot_home({"staff_confirmed": True})["ok"])
        self.assertTrue(any("원점 복귀 실패" in m["title"] for m in self.rep.messages if m["channel"] == "alert"))

    def test_guard_passes_other_calls(self):
        from agents.service import GuardedBackend
        from agents.tools import MockBackend
        ev = threading.Event()
        be = GuardedBackend(MockBackend(db={"A-1": {"status": "본센터 보관", "features": {}}}), ev)
        ev.set()
        self.assertIsNotNone(be.db_get_item("A-1"))           # DB 는 막지 않음
        self.assertTrue(be.robot_stop()["ok"])                # 정지는 막지 않음
        self.assertEqual(be.robot_grasp(), {"ok": False, "reason": "직원 정지 버튼"})


class HandoverTest(unittest.TestCase):
    """11/4: 로봇이 바구니에 넣으면 인계 대기, 직원이 건넨 뒤 인계 완료."""

    def setUp(self):
        self.rep = Reporter()
        self.svc = TowerService(demo_backend_factory(), self.rep)

    def status(self, item="A-W01"):
        return self.svc.backend_factory().db_get_item(item)["status"]

    def test_wait_then_done(self):
        out = self.svc.start_return(ok_payload(case="H1"))
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertIn("인계 대기", out["reason"])
        self.assertEqual(self.status(), "인계 대기")              # 시연 부품도 요청 사이에 상태가 이어짐
        res = self.svc.handover("H1", {"staff_confirmed": True})
        self.assertEqual(self.svc.backend_factory().db_get_item("A-W01")["changed_by"], "staff")
        self.assertEqual(res, {"case_id": "H1", "item_id": "A-W01", "status": "인계 완료"})
        self.assertEqual(self.status(), "인계 완료")
        self.assertTrue(any(m["channel"] == "progress" and "인계 완료" in m["title"] for m in self.rep.messages))
        with self.assertRaises(Conflict) as cm:
            self.svc.handover("H1", {"staff_confirmed": True})
        self.assertEqual(cm.exception.kind, "duplicate")

    def test_not_returned_case_cannot_handover(self):
        self.svc.start_return(ok_payload(case="H2", quiz_passed=False))
        with self.assertRaises(Conflict) as cm:
            self.svc.handover("H2", {"staff_confirmed": True})
        self.assertEqual(cm.exception.kind, "state")
        self.assertEqual(self.status(), "본센터 보관")

    def test_status_moved_elsewhere(self):
        self.svc.start_return(ok_payload(case="H3"))
        self.svc.backend_factory().db_set_status("A-W01", "반환 보류")   # 직원이 다른 처리를 한 경우
        with self.assertRaises(Conflict) as cm:
            self.svc.handover("H3", {"staff_confirmed": True})
        self.assertEqual(cm.exception.kind, "state")

    def test_bad_body(self):
        self.svc.start_return(ok_payload(case="H4"))
        for body in ({}, {"staff_confirmed": "true"}, {"staff_confirmed": True, "x": 1}, [], None):
            with self.assertRaises(RequestError, msg=repr(body)):
                self.svc.handover("H4", body)
        with self.assertRaises(NotFound):
            self.svc.handover("H9", {"staff_confirmed": True})

    def test_status_write_fail_is_503(self):
        self.svc.start_return(ok_payload(case="H5"))
        be = self.svc.backend_factory()
        orig = self.svc.backend_factory
        be.fallback.status_fail = {"인계 완료"}
        self.svc.backend_factory = lambda: be
        with self.assertRaises(Unavailable):
            self.svc.handover("H5", {"staff_confirmed": True})
        self.svc.backend_factory = orig
        self.assertEqual(self.status(), "인계 대기")

    def test_hold_from_wait(self):
        self.svc.start_return(ok_payload(case="H6"))
        for body in ({}, {"reason": "그냥"}, {"reason": "본인 아님", "memo": "이름"}, {"reason": None}):
            with self.assertRaises(RequestError, msg=repr(body)):
                self.svc.hold_handover("H6", body)
        res = self.svc.hold_handover("H6", {"reason": "본인 아님"})
        self.assertEqual(res["status"], "반환 보류")
        self.assertEqual(self.status(), "반환 보류")
        self.assertEqual(self.svc.backend_factory().db_get_item("A-W01")["changed_by"], "staff")
        self.assertTrue(any(m["channel"] == "alert" and "본인 아님" in m["title"] for m in self.rep.messages))
        with self.assertRaises(Conflict) as cm:
            self.svc.hold_handover("H6", {"reason": "기타"})
        self.assertEqual(cm.exception.kind, "duplicate")
        with self.assertRaises(Conflict) as cm:          # 보류된 물건은 인계 완료로 못 감
            self.svc.handover("H6", {"staff_confirmed": True})
        self.assertEqual(cm.exception.kind, "state")

    def test_hold_after_done_refused(self):
        self.svc.start_return(ok_payload(case="H7"))
        self.svc.handover("H7", {"staff_confirmed": True})
        with self.assertRaises(Conflict) as cm:
            self.svc.hold_handover("H7", {"reason": "분실인 거부"})
        self.assertEqual(cm.exception.kind, "state")
        self.assertEqual(self.status(), "인계 완료")

    def test_cross_check_all_ok_hands_over_and_frees_slot(self):
        """11/6 교차 검증: 대기 목록 → 답 보기 → 셋 다 맞음 → 인계 완료 + 칸 비움"""
        self.svc.storage.assign("A-W01", "R4-1")
        self.svc.start_return(ok_payload(case="X1"))
        q = self.svc.handover_queue()
        self.assertEqual([r["case_id"] for r in q], ["X1"])
        self.assertNotIn("mark", q[0]["public"])                     # 목록에는 비공개 특징 없음
        self.assertEqual(self.svc.handover_secret("X1")["secret"]["mark"], "별 모양 스티커")
        self.assertEqual(self.svc.storage.layout()["summary"]["used"], 1)   # 인계 대기 중에는 칸 예약
        res = self.svc.verify_handover("X1", {"item_match": True, "id_match": True, "feature_match": True})
        self.assertEqual((res["result"], self.status()), ("인계 완료", "인계 완료"))
        self.assertEqual(self.svc.storage.layout()["summary"]["used"], 0)
        self.assertEqual(self.svc.handover_queue(), [])
        self.assertTrue(any("교차 검증" in m["title"] for m in self.rep.messages))
        with self.assertRaises(Conflict):                             # 끝난 사례의 정답은 다시 안 보여 줌
            self.svc.handover_secret("X1")

    def test_cross_check_fail_holds_then_restock_to_same_slot(self):
        self.svc.storage.assign("A-W01", "R4-1")
        self.svc.storage.set_pose("R4-1", "pose_7")
        self.svc.start_return(ok_payload(case="X2"))
        res = self.svc.verify_handover("X2", {"item_match": True, "id_match": False, "feature_match": True})
        self.assertEqual((res["result"], res["reason"]), ("반환 보류", "본인 아님"))
        self.assertEqual(self.svc.storage.layout()["summary"]["used"], 1)   # 원래 칸 그대로 예약
        with self.assertRaises(RequestError):
            self.svc.restock("X2", {})
        out = self.svc.restock("X2", {"staff_confirmed": True})
        self.assertEqual((out["status"], out["slot"]), ("본센터 보관", {"slot_id": "R4-1", "pose_name": "pose_7"}))
        self.assertEqual(self.svc.storage.export()["inventory"], {"A-W01": {"section": "R4", "slot": "1"}})
        with self.assertRaises(Conflict):                             # 두 번 되돌릴 수 없음
            self.svc.restock("X2", {"staff_confirmed": True})

    def test_cross_check_reasons_and_bad_body(self):
        self.svc.start_return(ok_payload(case="X3"))
        for body in ({}, {"item_match": True, "id_match": True}, {"item_match": 1, "id_match": True, "feature_match": True},
                     {"item_match": True, "id_match": True, "feature_match": True, "memo": "x"}, None):
            with self.assertRaises(RequestError, msg=repr(body)):
                self.svc.verify_handover("X3", body)
        res = self.svc.verify_handover("X3", {"item_match": False, "id_match": True, "feature_match": True})
        self.assertEqual(res["reason"], "물건 다름")
        with self.assertRaises(Conflict):
            self.svc.verify_handover("X3", {"item_match": True, "id_match": True, "feature_match": True})
        self.assertIsNone(self.svc.item_photo("A-W01"))              # 시연 물건은 등록 사진 없음

    def test_item_photo_stays_inside_photo_dir(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            svc = TowerService(demo_backend_factory(), Reporter(), photo_dir=d)
            out = svc.create_item({"machine_id": "KIOSK-A", "place_text": "대합실",
                                   "photo": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="})
            p = svc.item_photo(out["item_id"])
            self.assertTrue(p is not None and Path(d).resolve() in p.parents)
            svc.intake.items[out["item_id"]]["photo_path"] = "../../etc/passwd"
            self.assertIsNone(svc.item_photo(out["item_id"]))

    def test_return_logs_storage_slot(self):
        """11/6: 반환을 시작하면 보관 칸·저장 자세(또는 기록 없음)를 관제 기록에 남김"""
        self.svc.start_return(ok_payload(case="S1"))
        self.assertTrue(any("보관 칸 기록 없음" in m.get("body", "") + m.get("title", "") for m in self.rep.messages))
        self.svc.handover("S1", {"staff_confirmed": True})
        self.svc.backend_factory().db_set_status("A-W02", "본센터 보관")
        self.svc.storage.assign("A-W02", "R4-1"); self.svc.storage.set_pose("R4-1", "pose_7")
        self.svc.start_return(ok_payload(case="S2", item="A-W02"))
        self.assertTrue(any("R4-1" in str(m) and "pose_7" in str(m) for m in self.rep.messages))

    def test_item_not_arrived_is_refused_without_side_effects(self):
        """11/6 시뮬레이션 허점: 역 상자 안(등록기계 보관) 물건을 찾으러 오면 로봇·상태를 건드리지 않고 409"""
        be = self.svc.backend_factory()
        be.db_set_status("A-W03", "등록기계 보관")
        with self.assertRaises(Conflict) as cm:
            self.svc.start_return(ok_payload(case="N1", item="A-W03"))
        self.assertEqual(cm.exception.kind, "not_arrived")
        self.assertEqual(self.status("A-W03"), "등록기계 보관")
        self.assertFalse(self.svc.recorder.has("N1"))

    def test_arrivals_recommend_and_place(self):
        """11/6 본센터 도착 처리: 역 키오스크 접수(등록기계 보관) → 도착 목록(역/본센터 구분·추천 칸) → 넣기 → 본센터 보관"""
        st = self.svc.create_item({"machine_id": "KIOSK-A", "place_text": "대합실"})["item_id"]
        ct = self.svc.create_item({"machine_id": "CENTER", "place_text": "대합실"})["item_id"]
        self.svc.set_item_features(st, {"qwen": {"category": "wallet", "colors": ["black"]}, "confidence": 0.9})
        arr = {a["item_id"]: a for a in self.svc.storage_arrivals()}
        self.assertEqual((arr[st]["where"], arr[ct]["where"]), ("station", "center"))
        self.assertEqual(arr[st]["category"], "지갑")
        self.assertIsNone(arr[ct]["recommended"])                    # 품목 미확인 → 추천 안 함
        order = list(arr)
        self.assertLess(order.index(ct), order.index(st))            # 본센터에 있는 물건 먼저, 역 상자 안은 뒤
        recs = [a["recommended"]["slot_id"] for a in arr.values() if a["recommended"]]
        self.assertEqual(len(recs), len(set(recs)))                  # 같은 칸을 두 번 추천하지 않음
        with self.assertRaises(RequestError):                        # 품목 미확인은 override 필요
            self.svc.place_item(ct, {"slot_id": "R2-1"})
        out = self.svc.place_item(ct, {"slot_id": "R2-1", "override_category": True})
        self.assertEqual((out["slot_id"], self.svc.intake.items[ct]["status"]), ("R2-1", "본센터 보관"))
        with self.assertRaises(Conflict):                            # 칸 하나에 물건 하나
            self.svc.place_item(st, {"slot_id": "R2-1", "override_category": True})
        for bad in ({}, {"slot_id": "R2-2", "x": 1}, {"slot_id": "R2-2", "override_category": "yes"}, None):
            with self.assertRaises(RequestError, msg=repr(bad)):
                self.svc.place_item(st, bad)
        with self.assertRaises(NotFound):
            self.svc.place_item("A-W99", {"slot_id": "R2-2"})
        self.assertNotIn(ct, [a["item_id"] for a in self.svc.storage_arrivals()])

    def test_schema_and_migration_list_all_statuses(self):
        from agents.contracts import ITEM_STATUS
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "center", "migrations", "004_handover_wait_1104.sql"), encoding="utf-8") as f:
            mig = f.read()
        for text in (schema_text(), mig):
            for s in ITEM_STATUS:
                self.assertIn(f"'{s}'", text)


if __name__ == "__main__":
    unittest.main()


class HealthReviewerDeviceTest(unittest.TestCase):
    """11/4: /health 에 LLM 검토 장치(cpu/gpu)를 보여 준다."""

    def test_device_shown(self):
        class R:
            device = "cpu"

            def __call__(self, summary):
                return "ok", ""
        h = TowerService(demo_backend_factory(), Reporter(), reviewer=R()).health()
        self.assertEqual((h["reviewer"], h["reviewer_device"]), (True, "cpu"))
        h = TowerService(demo_backend_factory(), Reporter()).health()
        self.assertEqual((h["reviewer"], h["reviewer_device"]), (False, None))
