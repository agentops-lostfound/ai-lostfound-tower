"""tools/reset_demo.py 시험 — 가짜 연결로 '시연 물건만, 미리보기는 안 바꿈, 기록 남김'을 확인."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import reset_demo as rd  # noqa: E402


class FakeConn:
    def __init__(self, rows):
        self.items = dict(rows)
        self.log, self.rolled_back, self.sql = [], False, []

    def __call__(self, dsn):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def rollback(self):
        self.rolled_back = True

    def cursor(self):
        db = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=()):
                db.sql.append(sql)
                if sql == rd.SQL_LIST:
                    self.rows = sorted((k, v) for k, v in db.items.items() if k in params[0])
                elif sql == rd.SQL_SET:
                    db.items[params[1]] = params[0]
                elif sql == rd.SQL_LOG:
                    db.log.append(params)

            def fetchall(self):
                return self.rows
        return Cur()


ROWS = {"A-W01": "인계 완료", "A-W02": "본센터 보관", "A-W03": "반환 보류", "B-9": "인계 완료"}


class ResetDemoTest(unittest.TestCase):
    def test_preview_changes_nothing(self):
        db = FakeConn(ROWS)
        out = rd.reset_demo("x", apply=False, connect=db)
        self.assertEqual(out, [("A-W01", "인계 완료"), ("A-W03", "반환 보류")])
        self.assertEqual(db.items["A-W01"], "인계 완료")
        self.assertEqual(db.log, [])
        self.assertTrue(db.rolled_back)

    def test_apply_resets_only_demo_items_and_logs(self):
        db = FakeConn(ROWS)
        rd.reset_demo("x", apply=True, connect=db)
        self.assertEqual(db.items["A-W01"], rd.HOME_STATUS)
        self.assertEqual(db.items["A-W03"], rd.HOME_STATUS)
        self.assertEqual(db.items["B-9"], "인계 완료")          # 진짜 접수 물건은 그대로
        self.assertEqual(db.log, [("A-W01", "인계 완료", rd.HOME_STATUS), ("A-W03", "반환 보류", rd.HOME_STATUS)])
        self.assertFalse(db.rolled_back)

    def test_already_home(self):
        db = FakeConn({k: rd.HOME_STATUS for k in rd.DEMO_ITEMS})
        self.assertEqual(rd.reset_demo("x", apply=True, connect=db), [])

    def test_sql_matches_schema(self):
        """changed_by='system' 과 home 상태가 schema·contracts 에서 허용되는 값인지"""
        from agents.contracts import ITEM_STATUS
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "center", "schema.sql"), encoding="utf-8") as f:
            schema = f.read()
        self.assertIn("'system'", schema[schema.index("changed_by"):schema.index("changed_by") + 120])
        self.assertIn(rd.HOME_STATUS, ITEM_STATUS)


if __name__ == "__main__":
    unittest.main()
