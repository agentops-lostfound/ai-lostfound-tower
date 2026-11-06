"""웹·관제탑 2단계 연결 시험 — 찾기 요청(POST /claims) → 방문 확인(POST /returns + claim_id)."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.claims import (ClaimError, MemoryClaimStore, PostgresClaimStore, SQL_GET, SQL_GET_QUIZ,  # noqa: E402
                           SQL_INSERT_CLAIM, SQL_INSERT_QUIZ, SQL_INSERT_RESERVATION, SQL_ITEM_EXISTS, SQL_LOCK,
                           SQL_NEXT_SEQ, SQL_VISITED, parse_claim, public_view, web_gates)
from agents.contracts import CLAIM_ID_RE, DECISION_REJECTED, DECISION_RETURNED  # noqa: E402
from agents.service import Conflict, NotFound, RequestError, TowerService, demo_backend_factory  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402


def web_payload(**over):
    p = {"consent": True, "name_masked": "변*원", "id_no_masked": "******-3******", "id_verified": True,
         "description": {"category": "지갑", "color": "검정", "mark": "별 모양 스티커"},
         "item_id": "A-W01", "quiz": [{"field": "mark", "passed": True}], "visit_date": "2026-11-04",
         "lost_station": "해운대"}
    p.update(over)
    return p


def visit(cid, **over):
    p = {"claim_id": cid, "visitor_id_match": True, "inner_feature_ok": True, "staff_confirmed": True}
    p.update(over)
    return p


class ParseClaimTest(unittest.TestCase):
    def test_ok(self):
        c = parse_claim(web_payload())
        self.assertEqual(c["item_id"], "A-W01")
        self.assertEqual(c["visit_date"], "2026-11-04")

    def test_rejects(self):
        bad = [
            web_payload(consent=False),                              # 필수 동의 없음
            web_payload(name_masked="변재원"),                        # 가리지 않은 이름
            web_payload(id_no_masked="010625-3123456"),               # 주민번호 원문
            web_payload(name_masked="010-1234-5678*"),                # 전화번호 모양
            web_payload(phone="010-1111-2222"),                       # 모르는 칸
            web_payload(item_id="L-0001"),                            # 접수 번호 형식 아님
            web_payload(description={"brand": "x"}),                 # 정한 칸 아님
            web_payload(quiz=[]),                                     # 확인 질문 없음
            web_payload(quiz=[{"field": "mark", "passed": "yes"}]),
            web_payload(visit_date="11/4"),
            web_payload(id_verified="true"),
        ]
        for p in bad:
            with self.assertRaises(ClaimError, msg=p):
                parse_claim(p)

    def test_web_gates(self):
        row = {"consented_at": "x", "id_verified": True, "quiz": [{"field": "mark", "passed": True},
                                                                  {"field": "color", "passed": False}]}
        self.assertEqual(web_gates(row), {"consent": True, "id_verified": True, "quiz_passed": False})
        self.assertFalse(web_gates({"consented_at": "x", "id_verified": True, "quiz": []})["quiz_passed"])


class MemoryStoreTest(unittest.TestCase):
    def test_ids_per_day(self):
        st = MemoryClaimStore()
        a = st.create(parse_claim(web_payload()), today=date(2026, 11, 3))
        b = st.create(parse_claim(web_payload()), today=date(2026, 11, 3))
        c = st.create(parse_claim(web_payload()), today=date(2026, 11, 4))
        self.assertEqual([a["claim_id"], b["claim_id"], c["claim_id"]],
                         ["C-20261103-0001", "C-20261103-0002", "C-20261104-0001"])
        self.assertTrue(all(CLAIM_ID_RE.match(x["claim_id"]) for x in (a, b, c)))

    def test_public_view_hides_description_and_id_no(self):
        row = MemoryClaimStore().create(parse_claim(web_payload()))
        view = public_view(row)
        self.assertNotIn("description", view)
        self.assertNotIn("id_no_masked", view)
        self.assertEqual(view["name_masked"], "변*원")


class TwoStepServiceTest(unittest.TestCase):
    def setUp(self):
        self.rep = Reporter()
        self.svc = TowerService(demo_backend_factory(), self.rep)

    def test_full_two_step_return(self):
        claim = self.svc.create_claim(web_payload())
        self.assertEqual(claim["web_gates"], {"consent": True, "id_verified": True, "quiz_passed": True})
        out = self.svc.start_return(visit(claim["claim_id"]))
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertEqual(out["claim_id"], claim["claim_id"])
        self.assertEqual(out["case_id"], "R-" + claim["claim_id"])
        self.assertEqual(self.svc.get_case(out["case_id"])["claim_id"], claim["claim_id"])
        self.assertEqual(self.svc.get_claim(claim["claim_id"])["status"], "visited")

    def test_same_claim_cannot_return_twice(self):
        cid = self.svc.create_claim(web_payload())["claim_id"]
        self.svc.start_return(visit(cid))
        with self.assertRaises(Conflict):
            self.svc.start_return(visit(cid, case_id="R-again"))   # 다른 사례 번호로도 안 됨

    def test_web_failure_cannot_be_overridden_by_staff(self):
        """직원 화면은 웹 관문을 보낼 수 없다 → 웹에서 확인 질문을 틀렸으면 반환 안 함"""
        cid = self.svc.create_claim(web_payload(quiz=[{"field": "mark", "passed": False}]))["claim_id"]
        with self.assertRaises(RequestError):
            self.svc.start_return({**visit(cid), "quiz_passed": True})
        out = self.svc.start_return(visit(cid))
        self.assertEqual(out["decision"], DECISION_REJECTED)
        self.assertEqual(self.svc.get_claim(cid)["status"], "booked")   # 반환 안 됐으니 예약은 그대로

    def test_visit_gate_false_rejects(self):
        cid = self.svc.create_claim(web_payload())["claim_id"]
        self.assertEqual(self.svc.start_return(visit(cid, visitor_id_match=False))["decision"], DECISION_REJECTED)

    def test_unknown_and_bad_claim(self):
        with self.assertRaises(NotFound):
            self.svc.start_return(visit("C-20261103-9999"))
        with self.assertRaises(RequestError):
            self.svc.start_return(visit("C-1"))
        with self.assertRaises(RequestError):
            self.svc.start_return({"claim_id": "C-20261103-0001", "visitor_id_match": True})
        with self.assertRaises(RequestError):
            self.svc.create_claim(web_payload(item_id="L-0001"))
        self.assertIsNone(self.svc.get_claim("C-20261103-9999"))

    def test_mark_visited_failure_alerts(self):
        class Broken(MemoryClaimStore):
            def mark_visited(self, claim_id):
                raise ConnectionError("DB 끊김")
        rep = Reporter()
        svc = TowerService(demo_backend_factory(), rep, claims=Broken())
        cid = svc.create_claim(web_payload())["claim_id"]
        self.assertEqual(svc.start_return(visit(cid))["decision"], DECISION_RETURNED)
        self.assertTrue(any("다시 반환 금지" in m["title"] for m in rep.messages if m["channel"] == "alert"))

    def test_old_one_step_form_still_works(self):
        from agents.service import GATE_FIELDS
        out = self.svc.start_return({"case_id": "OLD1", "item_id": "A-W01", **{g: True for g in GATE_FIELDS}})
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertNotIn("claim_id", out)


class FakePg:
    """PostgresClaimStore 용 가짜 DB(claim·quiz_attempt·reservation)"""

    def __init__(self, items=("A-W01",)):
        self.items, self.claims, self.quiz, self.res = set(items), {}, [], {}

    def __call__(self, dsn):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        db = self

        class Cur:
            rows = []

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, p=()):
                if sql == SQL_ITEM_EXISTS:
                    self.rows = [[1]] if p[0] in db.items else []
                elif sql == SQL_LOCK:
                    self.rows = []
                elif sql == SQL_NEXT_SEQ:
                    pre = p[0].rstrip("%")
                    self.rows = [[1 + sum(k.startswith(pre) for k in db.claims)]]
                elif sql == SQL_INSERT_CLAIM:
                    db.claims[p[0]] = {"name": p[1], "idno": p[2], "verified": p[3], "desc": p[4]}
                elif sql == SQL_INSERT_QUIZ:
                    db.quiz.append(p)
                elif sql == SQL_INSERT_RESERVATION:
                    db.res[p[0]] = [p[1], p[2], "booked"]
                elif sql == SQL_GET:
                    c = db.claims.get(p[0])
                    self.rows = [[p[0], "2026-11-03T10:00:00+00:00", c["name"], c["verified"], c["idno"], *db.res[p[0]],
                                  "2026-11-03T10:00:00+00:00"]] if c else []
                elif sql == SQL_GET_QUIZ:
                    self.rows = [[f, ok] for cid, _, f, ok in db.quiz if cid == p[0]]
                elif sql == SQL_VISITED:
                    db.res[p[0]][2] = "visited"
                else:
                    raise AssertionError(sql)

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return self.rows
        return Cur()


class PostgresStoreTest(unittest.TestCase):
    def test_create_get_visit(self):
        db = FakePg()
        st = PostgresClaimStore("postgresql://u:secret@h/db", connect=db)
        row = st.create(parse_claim(web_payload()), today=date(2026, 11, 3))
        self.assertEqual(row["claim_id"], "C-20261103-0001")
        self.assertEqual(web_gates(row), {"consent": True, "id_verified": True, "quiz_passed": True})
        self.assertIn('"mark": "별 모양 스티커"', db.claims["C-20261103-0001"]["desc"])   # 한글 그대로 JSON
        self.assertEqual(st.get("C-20261103-0001")["id_no_masked"], "******-3******")   # 키오스크 회수의 신분 대조용
        st.mark_visited("C-20261103-0001")
        self.assertEqual(st.get("C-20261103-0001")["status"], "visited")
        self.assertNotIn("secret", repr(st))

    def test_unknown_item_is_request_error(self):
        st = PostgresClaimStore("x", connect=FakePg(items=()))
        svc = TowerService(demo_backend_factory(), Reporter(), claims=st)
        with self.assertRaises(RequestError):
            svc.create_claim(web_payload())

    def test_schema_has_id_verified(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "center", "schema.sql"), encoding="utf-8") as f:
            self.assertIn("id_verified    BOOLEAN", f.read())
        with open(os.path.join(root, "center", "migrations", "002_claim_id_verified_1103.sql"), encoding="utf-8") as f:
            self.assertIn("ADD COLUMN IF NOT EXISTS id_verified", f.read())

    def test_quiz_fields_match_schema(self):
        import re
        from agents.claims import QUIZ_FIELDS
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "center", "schema.sql"), encoding="utf-8") as f:
            m = re.search(r"field\s+VARCHAR\(16\) NOT NULL CHECK \(field IN \((.*?)\)\)", f.read())
        self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), QUIZ_FIELDS)


if __name__ == "__main__":
    unittest.main()
