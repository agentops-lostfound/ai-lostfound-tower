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
    GATE_FIELDS, Conflict, RequestError, TowerService, demo_backend_factory, parse_request,
)
from discord_ops.reporter import Reporter  # noqa: E402


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


class RecordTest(unittest.TestCase):
    def test_record_has_no_pii_columns(self):
        row = to_record("A-1", {"case_id": "R1", "decision": "returned", "reason": "반환 완료", "steps": ["a"]})
        self.assertEqual(set(row), {"case_id", "item_id", "decision", "reason", "approved", "matched_object",
                                    "seconds", "created_at", "steps"})

    def test_memory_recorder_refuses_overwrite(self):
        r = MemoryRecorder()
        r.save("A-1", {"case_id": "R1", "decision": "returned", "reason": ""})
        with self.assertRaises(KeyError):
            r.save("A-1", {"case_id": "R1", "decision": "returned", "reason": ""})

    def test_schema_matches_record_columns(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents", "schema.sql")
        sql = open(path, encoding="utf-8").read()
        for col in ("case_id", "item_id", "decision", "reason", "approved", "matched_object", "seconds", "created_at"):
            self.assertIn(col, sql)


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

            def get(self, path):
                return self._reg("GET", path)

            def post(self, path):
                return self._reg("POST", path)

        fake = types.ModuleType("fastapi")
        fake.FastAPI, fake.HTTPException, fake.Body = FakeFastAPI, HTTPException, (lambda *a, **k: None)
        self.HTTPException = HTTPException
        sys.modules["fastapi"] = fake

    def tearDown(self):
        sys.modules.pop("fastapi", None)

    def test_routes_and_status_codes(self):
        from agents import api
        api.build_app(service())
        r = self.routes
        self.assertEqual(sorted(r), [("GET", "/health"), ("GET", "/returns"), ("GET", "/returns/{case_id}"),
                                     ("GET", "/tools"), ("POST", "/returns")])
        self.assertEqual(r[("POST", "/returns")](ok_payload())["decision"], DECISION_RETURNED)
        for payload, code in ((ok_payload(), 409), (ok_payload(case="R2", phone="010"), 422)):
            with self.assertRaises(self.HTTPException) as cm:
                r[("POST", "/returns")](payload)
            self.assertEqual(cm.exception.status_code, code)
        with self.assertRaises(self.HTTPException) as cm:
            r[("GET", "/returns/{case_id}")]("NONE")
        self.assertEqual(cm.exception.status_code, 404)
        self.assertEqual(r[("GET", "/returns/{case_id}")]("R1")["case_id"], "R1")
        self.assertEqual(len(r[("GET", "/tools")]()), 10)


if __name__ == "__main__":
    unittest.main()
