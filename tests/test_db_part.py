"""DB 부품·반환 기록(PostgreSQL) 시험.

- 기본: 가짜 연결로 약속(예외 안 던짐·상태 기록·중복 거부·DB 꺼짐 처리)을 확인 → 어느 PC에서나 돈다
- 실제 DB 시험: `docker compose up -d` 후 LF_TEST_DSN 을 주면 진짜 PostgreSQL 로도 돈다(psycopg 필요)
    $env:LF_TEST_DSN = "postgresql://lostfound:비밀번호@127.0.0.1:5434/lostfound"
    python -m unittest tests.test_db_part
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.db_part import SQL_GET_ITEM, SQL_LOCK_ITEM, SQL_LOG_STATUS, SQL_SET_STATUS, PostgresDbPart  # noqa: E402
from agents.records import PostgresRecorder  # noqa: E402
from agents.service import GATE_FIELDS, TowerService, Unavailable, demo_backend_factory  # noqa: E402
from agents.backends import CompositeBackend  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402


class FakeDB:
    """item·item_status_log·return_case·return_step 만 흉내 내는 아주 작은 가짜 DB."""

    def __init__(self):
        self.items = {"A-W01": ["A-W01", "본센터 보관", "지갑", {"color": "검정"}, {"mark": "별 모양 스티커"}, "W01"]}
        self.log, self.cases, self.steps, self.sql = [], {}, [], []

    def connect(self, dsn):
        db = self

        class Cur:
            rows = []

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                db.sql.append(sql)
                p = params
                if sql == SQL_GET_ITEM:
                    self.rows = [db.items[p[0]]] if p[0] in db.items else []
                elif sql == SQL_LOCK_ITEM:
                    self.rows = [[db.items[p[0]][1]]] if p[0] in db.items else []
                elif sql == SQL_SET_STATUS:
                    db.items[p[1]][1] = p[0]
                elif sql == SQL_LOG_STATUS:
                    db.log.append(p)
                elif sql.startswith("SELECT 1 FROM return_case"):
                    self.rows = [[1]] if p[0] in db.cases else []
                elif sql.startswith("INSERT INTO return_case"):
                    db.cases[p[0]] = list(p) + ["2026-11-03T10:00:00+09:00"]
                elif sql.startswith("INSERT INTO return_step"):
                    db.steps.append(p)
                elif sql.startswith("SELECT case_id") and "WHERE case_id" in sql:
                    self.rows = [db.cases[p[0]]] if p[0] in db.cases else []
                elif sql.startswith("SELECT step"):
                    self.rows = [[s, "2026-11-03T10:00:00+09:00"] for c, s in db.steps if c == p[0]]
                elif sql.startswith("SELECT case_id"):
                    self.rows = list(db.cases.values())[::-1][:p[0]]
                else:
                    raise AssertionError(sql)

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return self.rows

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cursor(self):
                return Cur()
        return Conn()


def down(dsn):
    raise ConnectionError("DB 꺼짐")


class DbPartTest(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.part = PostgresDbPart("postgresql://u:secret@h/db", connect=self.db.connect)

    def test_get_merges_public_and_private(self):
        it = self.part.db_get_item("A-W01")
        self.assertEqual(it["features"], {"color": "검정", "mark": "별 모양 스티커"})
        self.assertIsNone(self.part.db_get_item("없음"))

    def test_set_status_writes_log(self):
        self.assertTrue(self.part.db_set_status("A-W01", "반환 중")["ok"])
        self.assertEqual(self.db.items["A-W01"][1], "반환 중")
        self.assertEqual(self.db.log, [("A-W01", "본센터 보관", "반환 중")])

    def test_set_status_rejects(self):
        self.assertFalse(self.part.db_set_status("A-W01", "분실")["ok"])
        self.assertFalse(self.part.db_set_status("없음", "반환 중")["ok"])
        self.assertEqual(self.db.log, [])

    def test_db_down_never_raises(self):
        part = PostgresDbPart("x", connect=down)
        self.assertIsNone(part.db_get_item("A-W01"))
        r = part.db_set_status("A-W01", "반환 중")
        self.assertFalse(r["ok"])
        self.assertEqual(part.last_error, "ConnectionError")

    def test_secret_not_in_repr(self):
        self.assertNotIn("secret", repr(self.part))
        self.assertNotIn("secret", repr(PostgresRecorder("postgresql://u:secret@h/db", connect=self.db.connect)))

    def test_empty_dsn(self):
        with self.assertRaises(ValueError):
            PostgresDbPart("")


class RecorderServiceTest(unittest.TestCase):
    def gates(self):
        return {g: True for g in GATE_FIELDS}

    def test_full_flow_with_db_part_and_recorder(self):
        db = FakeDB()
        part = PostgresDbPart("x", connect=db.connect)
        svc = TowerService(lambda: CompositeBackend(db=part, fallback=demo_backend_factory()().fallback), Reporter(),
                           recorder=PostgresRecorder("x", connect=db.connect))
        out = svc.start_return({"case_id": "D1", "item_id": "A-W01", **self.gates()})
        self.assertEqual(out["decision"], "returned")
        self.assertTrue(out["recorded"])
        self.assertEqual([t for _, _, t in db.log], ["승인·수령 예약", "반환 중", "인계 완료"])
        row = svc.get_case("D1")
        self.assertEqual(row["item_id"], "A-W01")
        self.assertEqual(len(row["steps"]), len(out["steps"]))
        self.assertEqual(svc.recent()[0]["case_id"], "D1")

    def test_recorder_down_refuses_before_robot(self):
        svc = TowerService(demo_backend_factory(), Reporter(), recorder=PostgresRecorder("x", connect=down))
        with self.assertRaises(Unavailable):
            svc.start_return({"case_id": "D2", "item_id": "A-W01", **self.gates()})
        with self.assertRaises(Unavailable):
            svc.get_case("D2")
        self.assertFalse(svc.health()["busy"])

    def test_save_failure_after_return_still_answers(self):
        class SaveFails(PostgresRecorder):
            def save(self, item_id, outcome):
                raise ConnectionError("저장 중 끊김")
        rep = Reporter()
        svc = TowerService(demo_backend_factory(), rep, recorder=SaveFails("x", connect=FakeDB().connect))
        out = svc.start_return({"case_id": "D3", "item_id": "A-W01", **self.gates()})
        self.assertEqual(out["decision"], "returned")
        self.assertFalse(out["recorded"])
        self.assertTrue(any("기록 저장 실패" in m["title"] for m in rep.messages if m["channel"] == "alert"))


class McpDbModeTest(unittest.TestCase):
    """TOWER_DB=1 이면 MCP 의 db_get_item 이 DB 부품을 읽고, 비공개 특징은 여전히 빼는지"""

    def test_default_backend_switch(self):
        from agents import mcp_server
        from agents.tools import MockBackend
        self.assertIsInstance(mcp_server.default_backend({}), MockBackend)
        be = mcp_server.default_backend({"TOWER_DB": "1", "DATABASE_URL": "postgresql://u:p@h/db"})
        self.assertEqual(be.sources()["db_get_item"], "PostgresDbPart")
        self.assertEqual(be.sources()["vision_topview"], "가짜")

    def test_db_mode_tool_hides_private_features(self):
        import types
        registered = {}

        class FakeFastMCP:
            def __init__(self, name):
                pass

            def tool(self):
                def deco(fn):
                    registered[fn.__name__] = fn
                    return fn
                return deco
        fake = types.ModuleType("mcp.server.fastmcp")
        fake.FastMCP = FakeFastMCP
        sys.modules.update({"mcp": types.ModuleType("mcp"), "mcp.server": types.ModuleType("mcp.server"),
                            "mcp.server.fastmcp": fake})
        try:
            from agents import mcp_server
            from agents.tools import MockBackend
            be = CompositeBackend(db=PostgresDbPart("x", connect=FakeDB().connect), fallback=MockBackend())
            mcp_server.build_server(backend=be)
            rec = registered["db_get_item"]("A-W01")
            self.assertEqual(rec["features"], {"color": "검정"})        # mark(확인 질문 정답)는 빠짐
            self.assertIsNone(registered["db_get_item"]("없음"))
        finally:
            for k in ("mcp", "mcp.server", "mcp.server.fastmcp"):
                sys.modules.pop(k, None)


@unittest.skipUnless(os.environ.get("LF_TEST_DSN"), "실제 DB 시험: LF_TEST_DSN 이 없어 건너뜀")
class RealPostgresTest(unittest.TestCase):
    def test_round_trip(self):
        import uuid
        dsn = os.environ["LF_TEST_DSN"]
        part, rec = PostgresDbPart(dsn), PostgresRecorder(dsn)
        self.assertEqual(part.db_get_item("A-W03")["object_id"], "W03")
        svc = TowerService(lambda: CompositeBackend(db=part, fallback=demo_backend_factory()().fallback), Reporter(),
                           recorder=rec)
        case = "T-" + uuid.uuid4().hex[:10]
        out = svc.start_return({"case_id": case, "item_id": "A-W03", **{g: True for g in GATE_FIELDS}})
        self.assertEqual(out["decision"], "returned")
        self.assertTrue(rec.has(case))
        self.assertEqual(part.db_get_item("A-W03")["status"], "인계 완료")
        self.assertTrue(part.db_set_status("A-W03", "본센터 보관")["ok"])   # 다음 시험을 위해 되돌림


if __name__ == "__main__":
    unittest.main()
