"""습득물 접수(agents/intake.py) — 등록기계 화면 → 관제탑 입구 시험."""
import json
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import intake as ik  # noqa: E402
from agents.intake import IntakeError, MemoryIntakeStore, PostgresIntakeStore, parse_intake, receipt  # noqa: E402
from agents.service import NotFound, RequestError, TowerService, Unavailable, demo_backend_factory  # noqa: E402
from discord_ops.reporter import Reporter, find_pii  # noqa: E402

DAY = date(2026, 11, 3)
QWEN = {"category": "card_wallet", "colors": ["dark brown"], "shape": "rectangular", "materials": ["leather"],
        "logos_or_text": ["MIYUON"], "sticker_status": "absent", "stickers": [], "distinctive_features": []}


def p(**over):
    d = {"machine_id": "KIOSK-A", "place_text": "해운대역 승강장"}
    d.update(over)
    return d


class ParseTest(unittest.TestCase):
    def test_minimal_and_full(self):
        self.assertEqual(parse_intake(p()), {"machine_id": "KIOSK-A", "place_id": None, "place_text": "해운대역 승강장",
                                             "finder": None, "photo_path": None})
        full = parse_intake(p(place_id=2, finder={"name": " 김습득 ", "phone": "010-1234-5678"},
                              photo_path="photos/A/20261103_0001.jpg"))
        self.assertEqual(full["finder"], {"name": "김습득", "phone": "010-1234-5678"})
        self.assertEqual(full["place_id"], 2)

    def test_contact_is_optional(self):
        for f in ({}, {"name": "", "phone": "  "}, {"name": None}):
            self.assertIsNone(parse_intake(p(finder=f))["finder"], f)
        self.assertEqual(parse_intake(p(finder={"phone": "01012345678"}))["finder"], {"name": None, "phone": "01012345678"})
        self.assertEqual(parse_intake(p(finder={"name": "익명"}))["finder"], {"name": "익명", "phone": None})

    def test_rejects(self):
        bad = [p(place_text=""), p(place_text=None), p(place_text="가" * 129), p(machine_id="KIOSK-Z"),
               p(found_at="2026-11-03T10:00"), p(color="검정"),                    # 발견 시각·특징은 받지 않음
               p(place_id=True), p(place_id=0), p(place_id="1"),
               p(finder={"phone": "12345"}), p(finder={"email": "a@b.c"}), p(finder="010-1234-5678"),
               p(photo_path="../secret.jpg"), p(photo_path="/etc/x.jpg"), p(photo_path="사진.jpg"), "문자열"]
        for b in bad:
            with self.assertRaises(IntakeError, msg=b):
                parse_intake(b)

    def test_receipt_hides_contact(self):
        r = receipt({"item_id": "A-20261103-0001", "received_at": "t", "status": "등록기계 보관", "place_text": "x",
                     "contact_saved": True, "finder": {"name": "김습득", "phone": "010-1234-5678"}})
        self.assertEqual(set(r), {"item_id", "received_at", "status", "place_text", "contact_saved"})
        self.assertNotIn("010", json.dumps(r))


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.s = MemoryIntakeStore()

    def test_ids_per_machine_and_day(self):
        a1 = self.s.create(parse_intake(p()), DAY)["item_id"]
        a2 = self.s.create(parse_intake(p()), DAY)["item_id"]
        b1 = self.s.create(parse_intake(p(machine_id="KIOSK-C", place_text="서면역")), DAY)["item_id"]
        nxt = self.s.create(parse_intake(p()), date(2026, 11, 4))["item_id"]
        self.assertEqual((a1, a2, b1, nxt), ("A-20261103-0001", "A-20261103-0002", "S-20261103-0001", "A-20261104-0001"))
        self.assertEqual(self.s.items[a1]["status"], "등록기계 보관")

    def test_places_recommendation_order(self):
        first = self.s.places("KIOSK-A")
        self.assertEqual(first[0]["label"], "해운대역 승강장")
        toilet = next(x for x in first if x["label"] == "화장실")
        for _ in range(2):
            self.s.create(parse_intake(p(place_id=toilet["place_id"], place_text="화장실")), DAY)
        self.assertEqual(self.s.places("KIOSK-A")[0]["label"], "화장실")      # 많이 고른 장소가 앞으로
        self.assertEqual(self.s.places("CENTER")[0]["label"], "부산역 승강장")   # 11/6 본센터 = 부산역
        self.assertEqual(self.s.places("KIOSK-B"), [])                         # 11/6 중앙역 삭제
        other = self.s.places("KIOSK-C")[0]["place_id"]
        with self.assertRaises(IntakeError):                                   # 다른 역 추천 번호는 거부
            self.s.create(parse_intake(p(place_id=other)), DAY)

    def test_contact_saved_only_when_given(self):
        a = self.s.create(parse_intake(p()), DAY)
        b = self.s.create(parse_intake(p(finder={"phone": "010-2222-3333"})), DAY)
        self.assertFalse(a["contact_saved"]); self.assertTrue(b["contact_saved"])
        self.assertEqual(list(self.s.contacts), [b["item_id"]])

    def test_features_split(self):
        iid = self.s.create(parse_intake(p()), DAY)["item_id"]
        self.assertTrue(self.s.set_features(iid, ik.parse_features({"qwen": QWEN, "confidence": 0.8})))
        row = self.s.items[iid]
        self.assertEqual(row["category"], "지갑")
        self.assertEqual(row["features"], {"color": "갈색", "shape": "rectangular", "material": "leather", "confidence": 0.8})
        self.assertEqual(row["private_features"], {"mark": "없음", "visible_text": "MIYUON"})
        self.assertFalse(self.s.set_features("A-20261103-0099", {"category": "지갑"}))


class ServiceTest(unittest.TestCase):
    def svc(self, store=None):
        return TowerService(demo_backend_factory(), Reporter(), intake=store or MemoryIntakeStore())

    def test_flow_and_no_pii_out(self):
        s = self.svc()
        self.assertEqual(len(s.list_places("KIOSK-A")), 10)                  # 기본 10개(역마다 12개, 11/6)
        self.assertEqual(len(s.list_places("KIOSK-A", 30)), 12)
        r = s.create_item(p(finder={"name": "김습득", "phone": "010-1234-5678"}))
        self.assertRegex(r["item_id"], r"^A-\d{8}-0001$")
        self.assertTrue(r["contact_saved"])
        self.assertEqual(find_pii(json.dumps(r, ensure_ascii=False)), [])
        out = s.set_item_features(r["item_id"], {"qwen": QWEN})
        self.assertEqual(out["category"], "지갑")
        self.assertNotIn("visible_text", out["features"])                 # 비공개 특징(확인 질문 정답)은 안 돌려줌
        self.assertNotIn("mark", out["features"])

    def test_errors(self):
        s = self.svc()
        for call in (lambda: s.list_places("NOPE"), lambda: s.create_item(p(place_text="")),
                     lambda: s.set_item_features("bad id", {"qwen": QWEN}),
                     lambda: s.set_item_features("A-20261103-0001", {"qwen": "x"})):
            with self.assertRaises(RequestError):
                call()
        with self.assertRaises(NotFound):
            s.set_item_features("A-20261103-0009", {"qwen": QWEN})

    def test_store_down_is_unavailable(self):
        def down(dsn):
            raise ConnectionError("DB 꺼짐")
        s = self.svc(PostgresIntakeStore("postgresql://u:secret@h/db", connect=down))
        for call in (lambda: s.list_places("KIOSK-A"), lambda: s.create_item(p()),
                     lambda: s.set_item_features("A-20261103-0001", {"qwen": QWEN})):
            with self.assertRaises(Unavailable):
                call()
        self.assertNotIn("secret", repr(s.intake))


class FakePg:
    """item·place·finder_contact·item_status_log 만 흉내 내는 가짜 DB(SQL 순서와 거래 확인)."""

    def __init__(self):
        self.places = {1: ("2호선", "해운대", "해운대역 승강장", 0)}
        self.items, self.contacts, self.log, self.sql = {}, {}, [], []

    def connect(self, dsn):
        db = self

        class Cur:
            rows, rowcount = [], 0

            def __enter__(self): return self
            def __exit__(self, *a): return False

            def execute(self, sql, params=()):
                db.sql.append(sql)
                if sql == ik.SQL_MACHINE:
                    self.rows = [{"KIOSK-A": ("2호선", "해운대"), "CENTER": (None, None)}[params[0]]] \
                        if params[0] in ("KIOSK-A", "CENTER") else []
                elif sql == ik.SQL_PLACES:
                    self.rows = [(k, v[2]) for k, v in db.places.items() if v[:2] == params[:2]]
                elif sql == ik.SQL_PLACE_OK:
                    self.rows = [[1]] if params[0] in db.places and db.places[params[0]][:2] == params[1:] else []
                elif sql == ik.SQL_PLACE_USE:
                    l, s, lab, n = db.places[params[0]]; db.places[params[0]] = (l, s, lab, n + 1)
                elif sql == ik.SQL_LOCK_ITEM:
                    pass
                elif sql == ik.SQL_NEXT_ITEM_SEQ:
                    pre = params[0][:-1]
                    self.rows = [[1 + sum(1 for k in db.items if k.startswith(pre))]]
                elif sql == ik.SQL_INSERT_ITEM:
                    db.items[params[0]] = list(params); self.rows = [("2026-11-03T12:00:00+00:00", "등록기계 보관")]
                elif sql == ik.SQL_INSERT_CONTACT:
                    db.contacts[params[0]] = params[1:]
                elif sql == ik.SQL_LOG_FIRST:
                    db.log.append(params)
                elif sql == "SELECT 1 FROM item WHERE item_id = %s":
                    self.rows = [(1,)] if params[0] in db.items else []
                elif sql == ik.SQL_SET_FEATURES:
                    self.rowcount = 1 if params[3] in db.items else 0
                    if self.rowcount:
                        db.items[params[3]] += [params[0], json.loads(params[1]), json.loads(params[2])]
                else:
                    raise AssertionError(sql)

            def fetchone(self): return self.rows[0] if self.rows else None
            def fetchall(self): return self.rows

        class Conn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def cursor(self): return Cur()
        return Conn()


class PostgresStoreTest(unittest.TestCase):
    def setUp(self):
        self.db = FakePg()
        self.s = PostgresIntakeStore("x", connect=self.db.connect)

    def test_create_with_and_without_contact(self):
        a = self.s.create(parse_intake(p(place_id=1, finder={"name": "김습득"})), DAY)
        b = self.s.create(parse_intake(p()), DAY)
        self.assertEqual((a["item_id"], b["item_id"]), ("A-20261103-0001", "A-20261103-0002"))
        self.assertEqual(self.db.contacts, {"A-20261103-0001": ("김습득", None)})
        self.assertEqual(self.db.places[1][3], 1)
        self.assertEqual(self.db.log, [("A-20261103-0001", "등록기계 보관"), ("A-20261103-0002", "등록기계 보관")])
        self.assertLess(self.db.sql.index(ik.SQL_LOCK_ITEM), self.db.sql.index(ik.SQL_NEXT_ITEM_SEQ))
        self.assertEqual(self.s.places("KIOSK-A"), [{"place_id": 1, "label": "해운대역 승강장"}])
        self.assertEqual(self.s.places("CENTER"), [])

    def test_unknown_machine_or_place(self):
        with self.assertRaises(IntakeError):
            self.s.create(parse_intake(p(machine_id="KIOSK-Z", place_text="없는 역")), DAY)
        with self.assertRaises(IntakeError):
            self.s.create(parse_intake(p(place_id=7)), DAY)

    def test_set_features(self):
        iid = self.s.create(parse_intake(p()), DAY)["item_id"]
        self.assertTrue(self.s.set_features(iid, ik.parse_features({"qwen": QWEN})))
        cat, pub, priv = self.db.items[iid][-3:]
        self.assertEqual(cat, "지갑")
        self.assertFalse(set(pub) & {"mark", "visible_text"})            # DB CHECK 와 같은 나눔
        self.assertFalse(set(priv) & {"color", "shape", "material"})
        self.assertFalse(self.s.set_features("A-20261103-0099", {}))


if __name__ == "__main__":
    unittest.main()


class IntakePhotoTest(unittest.TestCase):
    """11/4: 등록기계 화면이 사진(data URL)을 POST /items 에 함께 보내면 관제탑이 저장하고 photo_path 를 채운다."""

    JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

    def url(self, raw, kind="image/jpeg"):
        import base64
        return f"data:{kind};base64," + base64.b64encode(raw).decode()

    def setUp(self):
        import tempfile
        from agents.service import TowerService, demo_backend_factory
        from discord_ops.reporter import Reporter
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = TowerService(demo_backend_factory(), Reporter(), photo_dir=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def files(self):
        from pathlib import Path
        return sorted(p for p in Path(self.tmp.name).rglob("*") if p.is_file())

    def test_decode(self):
        from agents.intake import IntakeError, decode_photo
        self.assertEqual(decode_photo(self.url(self.JPEG)), (self.JPEG, ".jpg"))
        self.assertEqual(decode_photo(self.url(self.PNG, "image/png"))[1], ".png")
        bad = [None, 123, "abc", self.url(self.JPEG, "image/gif"), "data:image/jpeg;base64,@@@",
               self.url(self.PNG, "image/jpeg"),                        # 내용은 png 인데 jpeg 라고 함
               self.url(b"", "image/jpeg"), self.url(b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024))]
        for b in bad:
            with self.assertRaises(IntakeError, msg=str(b)[:40]):
                decode_photo(b)

    def test_create_with_photo(self):
        out = self.svc.create_item({"machine_id": "KIOSK-A", "place_text": "2번 출구 계단", "photo": self.url(self.JPEG)})
        self.assertTrue(out["item_id"].startswith("A-"))
        files = self.files()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), self.JPEG)
        self.assertEqual(files[0].parent.name, "KIOSK-A")
        row = self.svc.intake.items[out["item_id"]]
        self.assertTrue(row["photo_path"].startswith("photos/KIOSK-A/") and row["photo_path"].endswith(".jpg"))
        self.assertNotIn("photo", out)                                     # 응답에 사진을 돌려주지 않음

    def test_bad_requests_leave_no_file(self):
        from agents.service import RequestError, Unavailable
        for body in ({"machine_id": "KIOSK-A", "place_text": "x", "photo": "abc"},
                     {"machine_id": "KIOSK-A", "place_text": "x", "photo": self.url(self.JPEG), "photo_path": "a.jpg"},
                     {"machine_id": "KIOSK-Z", "place_text": "x", "photo": self.url(self.JPEG)},
                     {"machine_id": "KIOSK-A", "photo": self.url(self.JPEG)}):     # 장소 없음
            with self.assertRaises(RequestError):
                self.svc.create_item(body)
        self.assertEqual(self.files(), [])
        def boom(intake):
            raise ConnectionError("DB 꺼짐")
        self.svc.intake.create = boom
        with self.assertRaises(Unavailable):
            self.svc.create_item({"machine_id": "KIOSK-A", "place_text": "x", "photo": self.url(self.JPEG)})
        self.assertEqual(self.files(), [])                                 # 저장 실패면 사진도 지움

    def test_without_photo_unchanged(self):
        out = self.svc.create_item({"machine_id": "KIOSK-C", "place_text": "대합실"})
        self.assertIsNone(self.svc.intake.items[out["item_id"]]["photo_path"])
        self.assertEqual(self.files(), [])
