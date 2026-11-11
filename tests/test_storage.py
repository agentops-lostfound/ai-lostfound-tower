"""보관함 정답지(agents/storage.py · 007 마이그레이션 · tools/storage_export.py) 시험 — 11/6 LF-8"""
import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agents.storage import (LAYOUT, ON_SHELF, MemoryStorageStore, PostgresStorageStore, StorageConflict,
                            StorageError)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "center" / "migrations" / "007_storage_slots_1106.sql"


def gunte_load_storage(storage: dict):
    """김건태 run_storage_check.load_storage 와 같은 검사(LF-3-yolo-aruco 브랜치, 11/5) — 형식 호환 확인용 복사"""
    sections, inventory = storage["sections"], storage["inventory"]
    occupied = set()
    for item_id, location in inventory.items():
        section, slot = location["section"], location["slot"]
        pose = sections[section]["slots"][slot]
        if not item_id.strip() or not isinstance(pose, str) or not pose.strip():
            raise ValueError("Every stored item requires an ID and a named pose")
        if (section, slot) in occupied:
            raise ValueError(f"Multiple items assigned to section {section}, slot {slot}")
        occupied.add((section, slot))
    return sections, inventory


class Items:
    """item_lookup 가짜: 물건 번호 → 상태·품목"""

    def __init__(self):
        self.db = {"A-W01": {"status": "본센터 보관", "category": "립밤"},
                   "A-W02": {"status": "본센터 보관", "category": "립밤"},
                   "A-W03": {"status": "확인 중", "category": "모형폰"},
                   "A-W04": {"status": "등록기계 보관", "category": "USB"},
                   "A-W05": {"status": "승인·수령 예약", "category": "보조배터리"}}

    def __call__(self, item_id):
        return self.db.get(item_id)


class MemoryStorageTest(unittest.TestCase):
    def setUp(self):
        self.items = Items()
        self.s = MemoryStorageStore(item_lookup=self.items)

    def test_layout_is_4_rows_by_2_plus_handover(self):
        lay = self.s.layout()
        self.assertEqual([x["code"] for x in lay["sections"]], ["R1", "R2", "R3", "R4", "H", "S"])
        sm = dict(lay["summary"])
        groups = sm.pop("groups")
        self.assertEqual(sm, {"shelf_slots": 8, "used": 0, "free": 8, "slots_without_pose": 8, "staff_shelf": 0})
        self.assertEqual([(g["key"], g["label"], g["rows"], g["used"], g["total"]) for g in groups],
                         [("phone", "휴대폰", ["R1"], 0, 2), ("보조배터리", "보조배터리", ["R2"], 0, 2),
                          ("핸드크림", "핸드크림", ["R3"], 0, 2), ("립밤", "립밤", ["R4"], 0, 2)])
        self.assertEqual((lay["sections"][5]["kind"], lay["sections"][5]["slots"]), ("staff", []))   # 선반 칸은 필요할 때 생김
        r1 = lay["sections"][0]
        self.assertEqual([x["slot_id"] for x in r1["slots"]], ["R1-1", "R1-2"])
        self.assertEqual({x["note"] for x in r1["slots"]}, {"45도 사선·상단 오른쪽 위"})   # 11/9: 폰은 45도 사선(탑뷰 '/')
        self.assertEqual(lay["sections"][4]["kind"], "handover")

    def test_assign_conflict_move_and_release(self):
        r = self.s.assign("A-W01", "R4-1")
        self.assertEqual((r["section"], r["slot"], r["pose_name"]), ("R4", "1", None))
        with self.assertRaises(StorageConflict):                     # 칸 하나에 물건 하나
            self.s.assign("A-W02", "R4-1")
        self.s.assign("A-W01", "R4-2")                                # 같은 물건을 옮기면 예전 칸은 빔
        lay = {x["slot_id"]: x for sec in self.s.layout()["sections"] for x in sec["slots"]}
        self.assertIsNone(lay["R4-1"]["item"])
        self.assertEqual(lay["R4-2"]["item"]["item_id"], "A-W01")
        self.assertEqual(self.s.release(item_id="A-W01"), {"ok": True, "slot_id": "R4-2", "item_id": "A-W01"})
        self.assertEqual(self.s.release(slot_id="R4-2"), {"ok": True, "slot_id": "R4-2", "item_id": None})

    def test_rejects_wrong_category_handover_and_off_shelf_status(self):
        with self.assertRaises(StorageError):                         # 립밤을 모형폰 행에
            self.s.assign("A-W01", "R1-1")
        self.assertEqual(self.s.assign("A-W01", "R1-1", override_category=True)["slot_id"], "R1-1")
        with self.assertRaises(StorageError):                         # 인계 구역은 보관 칸이 아님
            self.s.assign("A-W02", "H-1", override_category=True)
        with self.assertRaises(StorageConflict):                      # 아직 등록기계에 있는 물건
            self.s.assign("A-W04", "R4-1")
        with self.assertRaises(StorageError) as cm:
            self.s.assign("A-W99", "R4-1")
        self.assertTrue(cm.exception.not_found)
        with self.assertRaises(StorageError) as cm:
            self.s.assign("A-W02", "R9-1")
        self.assertTrue(cm.exception.not_found)
        for bad in (("A W01", "R1-1"), ("A-W01", "R1_1"), (None, "R1-1")):
            with self.assertRaises(StorageError):
                self.s.assign(*bad)
        with self.assertRaises(StorageError):
            self.s.release()
        with self.assertRaises(StorageError):
            self.s.release(item_id="A-W01", slot_id="R1-1")

    def test_export_matches_gunte_format_and_warns_without_pose(self):
        self.s.assign("A-W03", "R1-2")
        self.s.assign("A-W05", "R2-1")
        out = self.s.export()
        self.assertEqual(out["inventory"], {"A-W03": {"section": "R1", "slot": "2"},
                                            "A-W05": {"section": "R2", "slot": "1"}})
        self.assertEqual(out["sections"]["R1"]["slots"], {"1": None, "2": None})
        self.assertEqual(len(out["warnings"]), 2)
        with self.assertRaises(ValueError):                           # 자세가 비면 비전 쪽도 거절(안전)
            gunte_load_storage(out)
        self.s.set_pose("R1-2", "pose_1")
        self.s.set_pose("R2-1", "shelf_r3_1")
        out = self.s.export()
        self.assertEqual(out["warnings"], [])
        sections, inventory = gunte_load_storage(json.loads(json.dumps(out)))
        loc = inventory["A-W03"]
        self.assertEqual(sections[loc["section"]]["slots"][loc["slot"]], "pose_1")
        self.assertNotIn("bounds_mm", out["sections"]["R1"])
        self.s.set_bounds("R1", [0, 0, 250, 60])
        self.assertEqual(self.s.export()["sections"]["R1"]["bounds_mm"], [0.0, 0.0, 250.0, 60.0])
        for bad in ([0, 0, 0, 60], [0, 0, 250], "x", [0, 0, True, 60]):
            with self.assertRaises(StorageError):
                self.s.set_bounds("R1", bad)

    def test_items_leaving_shelf(self):
        self.s.assign("A-W01", "R4-1")
        self.s.assign("A-W02", "R4-2")
        self.items.db["A-W01"]["status"] = "반환 중"                  # 로봇이 집는 중: 칸은 유지, 내보내기에서는 빠짐
        self.assertNotIn("A-W01", self.s.export()["inventory"])
        self.assertEqual(self.s.layout()["summary"]["used"], 2)
        self.items.db["A-W01"]["status"] = "인계 대기"                # 11/11(021) 제출보관함에 놓임: 로봇 칸은 바로 빔
        self.assertEqual(self.s.layout()["summary"]["used"], 1)
        self.items.db["A-W01"]["status"] = "인계 완료"                # 건넴 → 칸 비움
        self.items.db["A-W02"]["status"] = "인계 완료"
        self.assertEqual(self.s.assign("A-W05", "R4-1", override_category=True)["slot_id"], "R4-1")   # 화면 새로고침 없이 바로 넣기
        self.s.release(slot_id="R4-1")
        self.assertEqual(self.s.layout()["summary"]["used"], 0)
        self.assertEqual(self.s.assign("A-W03", "R4-1", override_category=True)["slot_id"], "R4-1")

    def test_pose_validation(self):
        self.assertEqual(self.s.set_pose("R4-1", "pose_3")["pose_name"], "pose_3")
        self.assertIsNone(self.s.set_pose("R4-1", "")["pose_name"])
        for bad in ("Pose1", "1pose", "pose-1", "a" * 33, 3):
            with self.assertRaises(StorageError):
                self.s.set_pose("R4-1", bad)
        with self.assertRaises(StorageError):
            self.s.set_pose("R7-1", "pose_1")

    def test_record_check(self):
        row = self.s.record_check({"section": "R1", "expected_count": 2, "detected_count": 2, "status": "count_match"})
        self.assertEqual((row["id"], row["status"], row["item_id"]), (1, "count_match", None))
        self.s.record_check({"section": "R1", "expected_count": 2, "detected_count": None,
                             "status": "invalid_calibration", "item_id": "A-W03"})
        self.assertEqual([r["id"] for r in self.s.recent_checks()], [2, 1])
        for bad in ({"section": "R1", "expected_count": 2, "status": "ok"},
                    {"section": "R1", "expected_count": -1, "status": "count_match"},
                    {"section": "R1", "expected_count": 1, "status": "count_match", "image": "x.jpg"},
                    {"section": "R1", "expected_count": True, "status": "count_match"}, []):
            with self.assertRaises(StorageError):
                self.s.record_check(bad)
        with self.assertRaises(StorageError):
            self.s.record_check({"section": "R9", "expected_count": 1, "status": "count_match"})

    def test_without_lookup_allows_any_category(self):
        s = MemoryStorageStore()
        self.assertEqual(s.assign("A-W01", "R1-1")["slot_id"], "R1-1")
        with self.assertRaises(StorageError):
            s.assign("A-W02", "H-1")


class PhoneRowAndShelfTest(unittest.TestCase):
    """11/9 사용자 결정: R1 두 칸 = 휴대폰 전용(45도 사선) · R4 립밤 · R2 보조배터리 · R3 핸드크림, 맞는 칸이 없으면 직원 보관 선반"""

    def setUp(self):
        from agents.storage import recommend_slot, shelf_items, slot_groups, group_of
        self.recommend, self.shelf_items, self.groups, self.group_of = recommend_slot, shelf_items, slot_groups, group_of
        self.db = {f"A-W1{i}": {"status": "본센터 보관", "category": "모형폰"} for i in range(1, 4)}
        for i, cat in enumerate(["립밤", "USB", "지갑", "핸드크림", "보조배터리", "립밤", "USB"], start=1):
            self.db[f"A-W2{i}"] = {"status": "본센터 보관", "category": cat}
        self.db["A-W31"] = {"status": "등록기계 보관", "category": "립밤"}
        self.set_calls = []

        def setter(item_id, status):
            self.set_calls.append((item_id, status))
            self.db[item_id]["status"] = status
            return True
        self.s = MemoryStorageStore(item_lookup=self.db.get, status_setter=setter)

    def test_phone_only_r1(self):
        self.assertEqual(self.recommend(self.s.layout(), "모형폰")["slot_id"], "R1-1")
        self.s.assign("A-W11", "R1-1"); self.s.assign("A-W12", "R1-2")
        self.assertIsNone(self.recommend(self.s.layout(), "모형폰"))          # R1 이 차면 다른 행으로 보내지 않음
        with self.assertRaises(StorageError):
            self.s.assign("A-W13", "R4-1")                                   # 휴대폰을 R4 에 → 품목 다름
        with self.assertRaises(StorageError):
            self.s.assign("A-W21", "R1-1", override_category=False)          # 립밤을 R1 에

    def test_each_column_takes_its_category_near_robot_first(self):
        """11/9(015·016): 열마다 품목 하나 — R4 립밤 · R2 보조배터리 · R3 핸드크림(USB 는 운영 품목 아님). 1번 칸(먼 줄) 먼저"""
        rec = self.recommend(self.s.layout(), "립밤")
        self.assertEqual((rec["slot_id"], rec["other_row"]), ("R4-1", False))
        self.s.assign("A-W21", "R4-1")
        self.assertEqual(self.recommend(self.s.layout(), "립밤")["slot_id"], "R4-2")
        self.s.assign("A-W26", "R4-2")
        self.assertIsNone(self.recommend(self.s.layout(), "립밤"))           # 립밤 열이 차면 다른 열로 보내지 않음(칸 대기·선반)
        self.assertEqual(self.recommend(self.s.layout(), "보조배터리")["slot_id"], "R2-1")
        self.assertIsNone(self.recommend(self.s.layout(), "USB"))           # 016: USB 는 받는 열이 없음 → 직원 보관 선반
        self.s.assign("A-W24", "R3-1")
        self.assertEqual(self.recommend(self.s.layout(), "핸드크림")["slot_id"], "R3-2")
        with self.assertRaises(StorageError):
            self.s.assign("A-W22", "R3-2")                                   # USB 를 핸드크림 열에
        with self.assertRaises(StorageError):
            self.s.assign("A-W25", "R4-1", override_category=False)          # 보조배터리를 립밤 열에
        with self.assertRaises(StorageError):
            self.s.assign("A-W27", "R2-1")                                   # USB 를 보조배터리 열에
        g = {x["key"]: (x["rows"], x["used"], x["total"]) for x in self.groups(self.s.layout())}
        self.assertEqual(g, {"phone": (["R1"], 0, 2), "립밤": (["R4"], 2, 2), "보조배터리": (["R2"], 0, 2),
                             "핸드크림": (["R3"], 1, 2)})
        self.assertIsNone(self.group_of(self.groups(self.s.layout()), "USB"))
        self.assertIsNone(self.group_of(self.groups(self.s.layout()), "확인 불가"))

    def test_retired_category_lipbalm_has_no_column(self):
        """11/9 카드지갑은 운영 품목이 아님: 받는 열이 없어 추천 칸 없음 → 직원 보관 선반. 이미 들어 있던 카드지갑 기록은 그대로 읽힘"""
        self.assertIsNone(self.recommend(self.s.layout(), "지갑"))
        self.assertIsNone(self.group_of(self.groups(self.s.layout()), "지갑"))
        with self.assertRaises(StorageError):
            self.s.assign("A-W23", "R3-1")                                   # 품목 확인을 그대로 하면 어느 열도 안 받음
        self.assertEqual(self.s.assign("A-W23", "R3-1", override_category=True)["slot_id"], "R3-1")   # 직원이 강제로는 가능
        self.assertEqual(self.s.move_to_shelf("A-W23")["slot_id"], "S-1")

    def test_layout_follows_active_categories(self):
        """운영 품목(contracts.ACTIVE_CATEGORIES)이 한 곳에서 정해지고, 모든 운영 품목은 받는 열이 있다"""
        from agents.contracts import ACTIVE_CATEGORIES, MVP_CATEGORIES, RETIRED_CATEGORIES
        self.assertEqual(MVP_CATEGORIES, ACTIVE_CATEGORIES)
        self.assertEqual(RETIRED_CATEGORIES, ["지갑", "USB"])          # 11/11 020: 카드지갑 뺌(9일 016 에는 USB·립밤)
        rows = {c: a for c, _l, k, a, _n, _note in LAYOUT if k == "shelf"}
        self.assertTrue(all(rows.values()), rows)                            # 품목이 빠져 빈 열(= 제한 없음)이 되면 안 됨
        used = [c for a in rows.values() for c in a]
        self.assertEqual(sorted(used), sorted(ACTIVE_CATEGORIES))
        self.assertNotIn("지갑", used)

    def test_move_to_shelf_from_slot_and_from_kiosk(self):
        self.s.assign("A-W21", "R4-1")
        out = self.s.move_to_shelf("A-W21")
        self.assertEqual((out["slot_id"], out["from"]), ("S-1", "R4-1"))
        lay = self.s.layout()
        slots = {sl["slot_id"]: sl for sec in lay["sections"] for sl in sec["slots"]}
        self.assertIsNone(slots["R4-1"]["item"])                             # 칸이 빔
        self.assertEqual(lay["summary"]["staff_shelf"], 1)
        out = self.s.move_to_shelf("A-W31")                                  # 칸 대기 물건 → 직원이 가져와 바로 선반
        self.assertEqual((out["slot_id"], out["status"]), ("S-2", "본센터 보관"))
        self.assertEqual(self.set_calls, [("A-W31", "본센터 보관")])
        self.assertEqual(self.s.move_to_shelf("A-W31")["slot_id"], "S-2")     # 두 번 눌러도 그대로
        self.assertEqual([x["item_id"] for x in self.shelf_items(self.s.layout())], ["A-W21", "A-W31"])
        self.s.release(item_id="A-W21")
        self.assertEqual(self.s.move_to_shelf("A-W22")["slot_id"], "S-1")     # 빈 선반 자리 다시 씀
        self.db["A-W23"]["status"] = "인계 대기"
        with self.assertRaises(StorageConflict):
            self.s.move_to_shelf("A-W23")                                     # 반환 중·인계 대기는 못 옮김

    def test_shelf_not_exported_to_vision(self):
        from agents.storage import SLOT_POSES
        s = MemoryStorageStore(item_lookup=self.db.get, poses=SLOT_POSES)
        s.assign("A-W21", "R4-1")
        s.move_to_shelf("A-W22")
        out = s.export()
        self.assertNotIn("S", out["sections"])
        self.assertEqual(set(out["inventory"]), {"A-W21"})                   # 선반 물건은 로봇·탑뷰 대상이 아님
        self.assertEqual(out["warnings"], [])


class MigrationMatchesLayoutTest(unittest.TestCase):
    def test_seed_rows_match_layout(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        sections = re.findall(r"\('(\w+)',\s*'([^']+)',\s*'(shelf|handover|staff)',\s*'\{([^}]*)\}',\s*(\d+)\)", sql)
        fix14 = (ROOT / "center" / "migrations" / "014_storage_phone_rows_staff_shelf_1109.sql").read_text(encoding="utf-8")
        body14 = "\n".join(line for line in fix14.splitlines() if not line.lstrip().startswith("--"))
        sections += re.findall(r"\('(\w+)',\s*'([^']+)',\s*'(shelf|handover|staff)',\s*'\{([^}]*)\}',\s*(\d+)\)", body14)  # 11/9 구역 S
        got = {c: (lb, k, [x for x in cats.split(",") if x]) for c, lb, k, cats, _ in sections}
        # 009 → 014 → 015 가 바꾼 행(이름·품목)을 007 시작값에 차례로 적용하면 LAYOUT 과 같아야 한다(주석 속 되돌리기 문장은 빼고)
        for rel in ("009_storage_categories_photo_1106.sql", "014_storage_phone_rows_staff_shelf_1109.sql",
                    "015_storage_columns_no_lipbalm_1109.sql", "016_four_items_no_usb_1109.sql",
                    "018_columns_phone_battery_cream_wallet_1110.sql", "020_column_r4_lipbalm_1111.sql"):
            text = (ROOT / "center" / "migrations" / rel).read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
            fixes = re.findall(r"SET label = '([^']+)', allowed_categories = '\{([^}]*)\}'\s*"
                               r"WHERE section_code = '(\w+)' AND allowed_categories = '\{([^}]*)\}'", text)
            self.assertTrue(fixes, rel)
            for lb, cats, code, old in fixes:
                self.assertEqual(",".join(got[code][2]), old, f"{rel} {code}")
                got[code] = (lb, got[code][1], cats.split(","))
            # 016: 이름만 바꾸는 줄(품목은 그대로) — 옛 이름일 때만
            for lb, code, old, cats in re.findall(r"SET label = '([^']+)'\s*WHERE section_code = '(\w+)' AND label = '([^']+)'"
                                                  r" AND allowed_categories = '\{([^}]*)\}'", text):
                self.assertEqual((got[code][0], ",".join(got[code][2])), (old, cats), f"{rel} {code}")
                got[code] = (lb, got[code][1], got[code][2])
        self.assertEqual([(c, *got[c]) for c, _, _, _, _ in sections],
                         [(c, lb, k, al) for c, lb, k, al, _, _ in LAYOUT])
        self.assertIn("CHECK (kind IN ('shelf', 'handover', 'staff'))", body14)
        slots = re.findall(r"\('([A-Z]\d?-\d)',\s*'(\w+)',\s*(\d+),\s*(NULL|'[^']*')\)", sql)
        # 008 → 014 → 015 가 바꾼 메모(옛 값 → 새 값)를 007 시작값에 적용하면 LAYOUT 과 같아야 한다
        renames = {}
        for rel in ("008_storage_layout_photo_1106.sql", "014_storage_phone_rows_staff_shelf_1109.sql",
                    "015_storage_columns_no_lipbalm_1109.sql", "016_four_items_no_usb_1109.sql"):
            text = (ROOT / "center" / "migrations" / rel).read_text(encoding="utf-8")
            text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
            for new, old in re.findall(r"SET note = '([^']+)' WHERE .*?note = '([^']+)'", text):
                renames = {k: (new if v == old else v) for k, v in renames.items()}
                renames[old] = new
        got = [(sid, c, no, f"'{renames.get(n[1:-1], n[1:-1])}'" if n != "NULL" else n) for sid, c, no, n in slots]
        expect = [(f"{c}-{i}", c, str(i), "NULL" if note is None else f"'{note}'")
                  for c, _, _, _, n, note in LAYOUT for i in range(1, n + 1)]
        self.assertEqual(got, expect)

    def test_014_has_undo_notes_and_keeps_edited_values(self):
        """11/9: 되돌리기 방법을 주석으로 남기고, 화면에서 이미 바꾼 값은 덮어쓰지 않는다(옛 값일 때만 UPDATE)"""
        sql = (ROOT / "center" / "migrations" / "014_storage_phone_rows_staff_shelf_1109.sql").read_text(encoding="utf-8")
        self.assertIn("되돌리기", sql)
        body = [line for line in sql.splitlines() if line.strip() and not line.lstrip().startswith("--")]
        updates = " ".join(body).split(";")
        for u in updates:
            if "UPDATE storage_section" in u or "UPDATE storage_slot" in u:
                self.assertIn(" AND ", u, u)                             # 옛 값 조건
        self.assertIn("ON CONFLICT (section_code) DO NOTHING", sql)

    def test_015_has_undo_notes_and_keeps_edited_values(self):
        """11/9 015: 014 와 같은 방식 — 되돌리기 주석, 옛 값일 때만 UPDATE, 물건 배정(storage_assignment)은 건드리지 않음"""
        sql = (ROOT / "center" / "migrations" / "015_storage_columns_no_lipbalm_1109.sql").read_text(encoding="utf-8")
        self.assertIn("되돌리기", sql)
        body = " ".join(line for line in sql.splitlines() if line.strip() and not line.lstrip().startswith("--"))
        for u in body.split(";"):
            if u.strip():
                self.assertIn("UPDATE storage_", u)
                self.assertIn(" AND ", u, u)
        self.assertNotIn("storage_assignment", body)
        self.assertNotIn("립밤}", body.split("WHERE")[0])                     # 015 새 값에는 립밤이 없음

    def test_on_shelf_and_check_statuses_match_sql(self):
        from agents.storage import CHECK_STATUSES, RELEASE_STATUSES
        sql = MIGRATION.read_text(encoding="utf-8")
        block = sql[sql.index("status IN ('count_match'"):]
        self.assertEqual(re.findall(r"'(\w+)'", block[:block.index(")),")]), list(CHECK_STATUSES))
        latest = (ROOT / "center" / "migrations" / "011_storage_release_on_done_1106.sql").read_text(encoding="utf-8")
        self.assertIn("NEW.status IN ('" + "', '".join(RELEASE_STATUSES) + "')", latest)   # 11/6 인계 완료 때만
        from agents.contracts import ITEM_STATUS
        self.assertTrue(set(ON_SHELF) | set(RELEASE_STATUSES) <= set(ITEM_STATUS))

    def test_is_idempotent_style(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 4)
        self.assertEqual(sql.count("ON CONFLICT"), 2)          # 시작 배치 두 묶음(있으면 그대로)
        self.assertIn("DROP TRIGGER IF EXISTS", sql)


class SlotPosesTest(unittest.TestCase):
    """11/6 김건태 확정 칸 ↔ 로봇 저장 자세(013 마이그레이션)"""

    def test_migration_matches_constant(self):
        from agents.storage import LAYOUT, OUTLET_SEQUENCE, POSE_RE, SLOT_POSES
        sql = (ROOT / "center" / "migrations" / "013_slot_poses_1106.sql").read_text(encoding="utf-8")
        self.assertEqual(dict(re.findall(r"\('([A-Z]\d?-\d)', '(\w+)'\)", sql)), SLOT_POSES)
        self.assertIn("s.pose_name IS NULL", sql)                          # 직접 넣은 이름은 덮어쓰지 않음
        slots = {f"{code}-{i}" for code, _l, _k, _a, n, _note in LAYOUT for i in range(1, n + 1)}
        self.assertEqual(set(SLOT_POSES), slots)                           # 칸 9개 모두
        self.assertEqual(len(set(SLOT_POSES.values())), 9)                 # 자세 이름 겹침 없음
        self.assertTrue(all(POSE_RE.match(p) for p in list(SLOT_POSES.values()) + list(OUTLET_SEQUENCE)))
        self.assertEqual(OUTLET_SEQUENCE[1:3], ("close", "open"))

    def test_memory_store_with_poses_exports_without_warning(self):
        from agents.storage import SLOT_POSES
        s = MemoryStorageStore(poses=SLOT_POSES)
        self.assertEqual(s.layout()["summary"]["slots_without_pose"], 0)
        s.assign("A-W01", "R4-2")
        out = s.export()
        self.assertEqual(out["warnings"], [])
        self.assertEqual(out["sections"]["R4"]["slots"]["2"], "pose_8")
        self.assertEqual(out["sections"]["H"]["slots"]["1"], "close")
        self.assertEqual(MemoryStorageStore().layout()["summary"]["slots_without_pose"], 8)   # poses 없이 = 예전 그대로

    def test_service_default_store_has_team_poses(self):
        from agents.api import demo_backend_factory
        from agents.service import TowerService
        from discord_ops.reporter import Reporter
        svc = TowerService(demo_backend_factory(), Reporter())
        lay = svc.storage.layout()
        self.assertEqual(lay["summary"]["slots_without_pose"], 0)
        poses = {sl["slot_id"]: sl["pose_name"] for sec in lay["sections"] for sl in sec["slots"]}
        self.assertEqual((poses["R1-1"], poses["R4-2"], poses["H-1"]), ("pose_1", "pose_8", "close"))


class StorageExportToolTest(unittest.TestCase):
    def test_demo_and_store_exit_codes(self):
        from tools import storage_export
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(storage_export.main(["--demo"]), 0)
        self.assertEqual(set(json.loads(out.getvalue())), {"sections", "inventory", "warnings", "exported_at"})
        s = MemoryStorageStore()
        s.assign("A-W01", "R4-1")
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(storage_export.main([], store=s), 2)       # 자세 없는 칸에 물건 → 경고
        self.assertIn("R4-1", err.getvalue())

    def test_no_dsn(self):
        from tools import storage_export
        old = os.environ.pop("DATABASE_URL", None)
        try:
            import tools.envfile as ef
            orig, ef.load_env = ef.load_env, (lambda *a, **k: None)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(storage_export.main([]), 1)
        finally:
            ef.load_env = orig
            if old is not None:
                os.environ["DATABASE_URL"] = old

    def test_postgres_store_hides_dsn(self):
        self.assertEqual(repr(PostgresStorageStore("postgresql://u:secret@h/db")), "PostgresStorageStore(dsn=***)")
        with self.assertRaises(ValueError):
            PostgresStorageStore("")


@unittest.skipUnless(os.environ.get("LF_SUPPORT_TEST_DSN"), "disposable PostgreSQL not configured")
class PostgresStorageTest(unittest.TestCase):
    """버리는 DB lf_support_test 에서만(tests/test_center_postgres.py 와 같은 규칙)"""

    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.dsn = os.environ["LF_SUPPORT_TEST_DSN"]
        with psycopg.connect(cls.dsn) as conn:
            if conn.info.dbname != "lf_support_test":
                raise RuntimeError("Integration tests require disposable database lf_support_test")
            conn.execute((ROOT / "center/schema.sql").read_text(encoding="utf-8"))
            for path in sorted((ROOT / "center/migrations").glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))

    def setUp(self):
        import psycopg
        with psycopg.connect(self.dsn) as conn:
            conn.execute("TRUNCATE storage_assignment, inventory_check")
            conn.execute("UPDATE storage_slot SET pose_name = NULL")
            conn.execute("INSERT INTO machine(machine_id,kind,line,station) VALUES('KIOSK-A','kiosk','1호선','중앙') "
                         "ON CONFLICT DO NOTHING")
            for iid, st, cat in (("A-W01", "본센터 보관", "립밤"), ("A-W02", "본센터 보관", "립밤"),
                                 ("A-W04", "등록기계 보관", "USB")):
                conn.execute("INSERT INTO item(item_id,machine_id,place_text,category,status) VALUES(%s,'KIOSK-A','시험',%s,%s) "
                             "ON CONFLICT (item_id) DO UPDATE SET status=EXCLUDED.status, category=EXCLUDED.category",
                             (iid, cat, st))
        self.s = PostgresStorageStore(self.dsn)

    def test_round_trip_and_trigger(self):
        import psycopg
        self.s.assign("A-W01", "R4-1")                                 # 11/9 015: 립밤은 R4 열
        with self.assertRaises(StorageConflict):
            self.s.assign("A-W02", "R4-1")
        with self.assertRaises(StorageConflict):
            self.s.assign("A-W04", "R3-1")                             # USB 열이지만 아직 등록기계에 있음
        with self.assertRaises(StorageError):
            self.s.assign("A-W02", "R1-1")
        with self.assertRaises(StorageError):
            self.s.assign("A-W02", "R3-1")                             # 립밤을 핸드크림 열에
        self.s.assign("A-W01", "R4-2")
        self.s.set_pose("R4-2", "pose_2")
        out = self.s.export()
        self.assertEqual(out["inventory"], {"A-W01": {"section": "R4", "slot": "2"}})
        gunte_load_storage(out)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE item SET status='인계 대기' WHERE item_id='A-W01'")
        self.assertEqual(self.s.layout()["summary"]["used"], 1)       # 11/6 인계 대기는 칸 예약 유지
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE item SET status='인계 완료' WHERE item_id='A-W01'")
        self.assertEqual(self.s.layout()["summary"]["used"], 0)
        row = self.s.record_check({"section": "R3", "expected_count": 0, "detected_count": 0, "status": "count_match"})
        self.assertEqual(self.s.recent_checks(5)[0]["id"], row["id"])
