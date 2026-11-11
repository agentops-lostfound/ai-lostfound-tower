"""tools/purge_sim_items.py — 지난 가상 시연 물건 정리(11/10). 진짜 PostgreSQL 시험은 LF_TEST_DATABASE_URL 이 있을 때만"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.purge_sim_items import main, pick, purge_sim  # noqa: E402


class PickTest(unittest.TestCase):
    def test_before_today_only_unless_all(self):
        rows = ["A-20261109-0001", "A-20261110-0001", "H-20261108-0002", "A-W01"]
        self.assertEqual(pick(rows, "20261110", False), ["A-20261109-0001", "H-20261108-0002"])
        self.assertEqual(pick(rows, "20261110", True), sorted(rows))

    def test_bad_before_and_no_dsn(self):
        self.assertEqual(main(["--before", "11-10"]), 2)
        old = os.environ.pop("DATABASE_URL", None)
        try:
            import tools.envfile as ef
            keep = ef.load_env
            ef.load_env = lambda *a, **k: None
            try:
                self.assertEqual(main([]), 2)
            finally:
                ef.load_env = keep
        finally:
            if old is not None:
                os.environ["DATABASE_URL"] = old


@unittest.skipUnless(os.environ.get("LF_TEST_DATABASE_URL"), "LF_TEST_DATABASE_URL(시험용 PostgreSQL)이 있을 때만")
class RealPostgresTest(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.dsn = os.environ["LF_TEST_DATABASE_URL"]
        self.pg = psycopg.connect(self.dsn, autocommit=True)
        self.clean()

    def tearDown(self):
        self.clean()
        self.pg.close()

    def clean(self):
        with self.pg.cursor() as cur:
            cur.execute("TRUNCATE return_step, return_case, reservation, quiz_attempt, claim_candidate, claim, storage_assignment, "
                        "finder_contact, item_status_log, inventory_check, collection_item, item CASCADE")

    def q(self, sql, *args):
        with self.pg.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall() if cur.description else None

    def item(self, iid, sim, status="본센터 보관"):
        self.q("INSERT INTO item (item_id, machine_id, place_text, status, category, object_id) VALUES (%s, 'KIOSK-A', 'x', %s, '핸드크림', %s)",
               iid, status, "SIM" if sim else None)

    def claim(self, cid, iid):
        self.q("INSERT INTO claim (claim_id, consented_at, name_masked, id_no_masked) VALUES (%s, now(), '홍*동', '******-1******')", cid)
        self.q("INSERT INTO reservation (claim_id, item_id, visit_date) VALUES (%s, %s, CURRENT_DATE)", cid, iid)
        self.q("INSERT INTO quiz_attempt (claim_id, item_id, field, passed) VALUES (%s, %s, 'place', true)", cid, iid)

    def test_old_sim_rows_go_real_and_today_stay(self):
        old, today, real = "A-20261109-0001", "A-20261110-0001", "A-20261109-0002"
        self.item(old, True)
        self.item(today, True)
        self.item(real, False)
        self.q("INSERT INTO item_status_log (item_id, from_status, to_status, changed_by) VALUES (%s, NULL, '본센터 보관', 'system')", old)
        self.q("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES ('R3-1', %s, 'system')", old)
        self.q("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES ('R3-2', %s, 'staff')", real)
        self.claim("C-20261109-0001", old)
        self.q("INSERT INTO return_case (case_id, item_id, claim_id, decision, reason, approved) VALUES ('R-C-20261109-0001', %s, "
               "'C-20261109-0001', 'returned', 'x', true)", old)
        self.q("INSERT INTO return_step (case_id, step) VALUES ('R-C-20261109-0001', '집기 성공')")
        self.claim("C-20261109-0002", real)                                     # 진짜 물건의 찾기 요청

        prev = purge_sim(self.dsn, apply=False, before="20261110")
        self.assertEqual((prev["items"], prev["claims"], prev["cases"], prev["slots"], prev["kept_today"]),
                         ([old], 1, 1, 1, 1))
        self.assertEqual(self.q("SELECT count(*) FROM item")[0][0], 3)           # 미리보기는 아무것도 안 지움

        purge_sim(self.dsn, apply=True, before="20261110")
        self.assertEqual(sorted(r[0] for r in self.q("SELECT item_id FROM item")), sorted([today, real]))
        self.assertEqual(self.q("SELECT claim_id FROM claim"), [("C-20261109-0002",)])
        self.assertEqual(self.q("SELECT slot_id FROM storage_assignment"), [("R3-2",)])
        for t in ("return_step", "return_case", "item_status_log"):
            self.assertEqual(self.q(f"SELECT count(*) FROM {t}")[0][0], 0, t)

        purge_sim(self.dsn, apply=True, include_all=True)                       # --all: 오늘 가상 물건까지, 진짜는 그대로
        self.assertEqual([r[0] for r in self.q("SELECT item_id FROM item")], [real])

    def test_staff_slot_on_sim_item_is_kept(self):
        old = "A-20261109-0003"
        self.item(old, True)
        self.q("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES ('R1-1', %s, 'staff')", old)
        r = purge_sim(self.dsn, apply=True, before="20261110")
        self.assertEqual((r["items"], r["held_by_staff_slot"]), ([], [old]))
        self.assertEqual(self.q("SELECT count(*) FROM item")[0][0], 1)


if __name__ == "__main__":
    unittest.main()
