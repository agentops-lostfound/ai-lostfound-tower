"""11/11 크기 측정(agents/size_measure.py) — Qwen 이 핸드크림을 립밤으로 읽은 문제(A-20261111-0092)를 크기로 바로잡기.
합성 펠트 사진(잔무늬 있는 회색 바닥 + 물건 사각형)으로 길이·폭을 재고, 키오스크가 잘라 키운 사진은 자르기 정보로 되돌려 잰다"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import size_measure as sm  # noqa: E402


def felt(path, length, width, angle=0.0, seed=1):
    """960×720 회색 펠트(잔무늬) 위 분홍 사각형 물건"""
    import numpy as np
    from PIL import Image, ImageDraw
    rng = np.random.default_rng(seed)
    base = np.full((720, 960, 3), (150, 140, 160), np.float32) + rng.normal(0, 6, (720, 960, 1))
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))
    mask = Image.new("L", (960, 720), 0)
    a = np.deg2rad(angle)
    u, v = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
    c = np.array([480.0, 360.0])
    ImageDraw.Draw(mask).polygon([tuple(c + sx * length / 2 * u + sy * width / 2 * v) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))], fill=255)
    im.paste(Image.new("RGB", (960, 720), (235, 150, 180)), (0, 0), mask)
    im.save(path, quality=90)
    return im


class DecideTest(unittest.TestCase):
    def m(self, length, width):
        g, why = sm.classify(length, width)
        return {"found": True, "length": length, "width": width, "size_group": g, "reason": why}

    def test_groups_from_1111_felt_photos(self):
        self.assertEqual(sm.classify(215, 68)[0], "립밤")
        self.assertEqual(sm.classify(382, 127)[0], "핸드크림")
        self.assertEqual(sm.classify(455, 218)[0], "휴대폰·보조배터리")
        self.assertEqual(sm.classify(420, 210)[0], "휴대폰·보조배터리")
        self.assertIsNone(sm.classify(300, 100)[0])                    # 어느 품목 크기도 아님 → 바꾸지 않음

    def test_cream_read_as_lipbalm_is_fixed_and_right_answers_kept(self):
        self.assertEqual(sm.decide("립밤", self.m(382, 127))[:2], ("핸드크림", True))       # 11/11 A-…-0092
        self.assertEqual(sm.decide("핸드크림", self.m(215, 68))[:2], ("립밤", True))
        self.assertEqual(sm.decide("핸드크림", self.m(382, 127))[:2], ("핸드크림", False))
        self.assertEqual(sm.decide("확인 불가", self.m(215, 68))[:2], ("립밤", True))        # 못 읽은 것도 채움
        self.assertEqual(sm.decide("립밤", self.m(455, 218))[:2], ("모형폰", True))         # 크게 다르면 가까운 쪽
        self.assertEqual(sm.decide("USB", self.m(215, 68))[:2], ("USB", False))             # 운영 품목 밖은 그대로

    def test_phone_battery_only_outside_band(self):
        self.assertEqual(sm.decide("모형폰", self.m(420, 210))[:2], ("보조배터리", True))
        self.assertEqual(sm.decide("보조배터리", self.m(458, 220))[:2], ("모형폰", True))
        self.assertEqual(sm.decide("모형폰", self.m(438, 215))[:2], ("모형폰", False))      # 가운데 띠 → Qwen 그대로
        self.assertEqual(sm.decide("보조배터리", self.m(438, 215))[:2], ("보조배터리", False))

    def test_no_measure_keeps_qwen(self):
        self.assertEqual(sm.decide("립밤", None)[:2], ("립밤", False))
        self.assertEqual(sm.decide("립밤", {"found": False, "reason": "펠트 아님"})[:2], ("립밤", False))

    def test_clean_rejects_bad_values(self):
        self.assertIsNone(sm.clean("x"))
        c = sm.clean({"found": True, "length": True, "width": 3, "size_group": "로켓"})
        self.assertFalse(c["found"])
        self.assertIsNone(c["size_group"])
        feats = {"category": "립밤", "color": "분홍"}
        self.assertEqual(sm.apply_to_features(feats, {"found": True, "length": 1e9, "size_group": "핸드크림"}), feats)


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_frame_sizes(self):
        for (L, W, ang), want in (((382, 127, 0), "핸드크림"), ((215, 68, 45), "립밤"), ((455, 218, 30), "휴대폰·보조배터리")):
            p = self.d / f"f{L}.jpg"
            felt(p, L, W, ang)
            m = sm.measure(p)
            self.assertEqual(m["size_group"], want, m)
            self.assertAlmostEqual(m["length"], L, delta=L * 0.04)

    def test_cropped_photo_uses_saved_geometry(self):
        im = felt(self.d / "full.jpg", 382, 127, 20)
        x, y, w, h = 230, 170, 520, 380
        up = 720 / w
        p = self.d / "crop.jpg"
        im.crop((x, y, x + w, y + h)).resize((round(w * up), round(h * up))).save(p, quality=90)
        self.assertFalse(sm.measure(p)["found"])                       # 자르기 정보 없음 → 재지 않음
        p.with_suffix(".json").write_text(json.dumps({"crop": [x, y, w, h], "frame": [960, 720], "up": round(w * up) / w}))
        m = sm.measure(p)
        self.assertEqual(m["size_group"], "핸드크림", m)
        self.assertAlmostEqual(m["length"], 382, delta=15)

    def test_scale_env_for_other_camera_setting(self):
        p = self.d / "f.jpg"
        felt(p, 300, 100)                                              # 해상도·높이가 바뀌어 작게 찍힘
        self.assertIsNone(sm.measure(p, {})["size_group"])
        self.assertEqual(sm.measure(p, {"TOWER_SIZE_SCALE": "1.27"})["size_group"], "핸드크림")

    def test_paper_background_is_not_measured(self):
        from PIL import Image
        p = self.d / "paper.jpg"
        Image.new("RGB", (960, 720), (200, 200, 205)).save(p)
        self.assertFalse(sm.measure(p)["found"])


class IntakeTest(unittest.TestCase):
    QWEN = {"category": "lip_balm", "colors": ["pink"], "shape": None, "materials": [], "logos_or_text": [],
            "sticker_status": "unknown", "stickers": [], "distinctive_features": []}

    def test_parse_features_applies_size_after_color(self):
        from agents.intake import parse_features
        size = {"found": True, "length": 382, "width": 127, "size_group": "핸드크림", "reason": "r"}
        f = parse_features({"qwen": self.QWEN, "size_measure": size})
        self.assertEqual((f["category"], f["color"]), ("핸드크림", "분홍"))
        self.assertEqual(parse_features({"qwen": self.QWEN})["category"], "립밤")
        from agents.intake import IntakeError
        with self.assertRaises(IntakeError):
            parse_features({"qwen": self.QWEN, "size_measure": "x"})

    def test_parse_geom(self):
        from agents.intake import parse_geom
        self.assertEqual(parse_geom({"crop": [1, 2, 3, 4], "frame": [960, 720], "up": 1.5}),
                         {"crop": [1, 2, 3, 4], "frame": [960, 720], "up": 1.5})
        self.assertEqual(parse_geom({"crop": None, "frame": [960, 720], "up": 1})["crop"], None)
        for bad in ("x", {"frame": [0, 720]}, {"frame": [960, 720], "up": 99}, {"frame": [960, 720], "evil": 1},
                    {"crop": [1, 2, 3], "frame": [960, 720]}, {"frame": [960, True]}):
            self.assertIsNone(parse_geom(bad), bad)

    def test_service_saves_geom_next_to_photo(self):
        import base64
        import io
        from PIL import Image
        from agents.service import TowerService, demo_backend_factory
        from discord_ops.reporter import Reporter
        with tempfile.TemporaryDirectory() as d:
            svc = TowerService(demo_backend_factory(), Reporter(), photo_dir=d)
            buf = io.BytesIO()
            Image.new("RGB", (40, 30), (100, 100, 100)).save(buf, "JPEG")
            url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            geom = {"crop": [10, 20, 300, 200], "frame": [960, 720], "up": 2.4}
            rec = svc.create_item({"machine_id": "KIOSK-A", "place_text": "중앙역", "photo": url, "photo_geom": geom})
            rel = svc.intake.photo_path(rec["item_id"])
            side = (Path(d) / rel).with_suffix(".json")
            self.assertEqual(json.loads(side.read_text()), geom)
            rec2 = svc.create_item({"machine_id": "KIOSK-A", "place_text": "중앙역", "photo": url, "photo_geom": {"evil": 1}})
            self.assertFalse((Path(d) / svc.intake.photo_path(rec2["item_id"])).with_suffix(".json").exists())   # 틀린 정보는 버리고 접수는 됨


class WorkerTest(unittest.TestCase):
    def test_hint_appended_once_and_switch(self):
        from tools import intake_qwen_worker as w
        import vision.item_features as vf
        orig = vf.PROMPT
        try:
            self.assertTrue(w.hint_prompt())
            self.assertTrue(w.hint_prompt())
            self.assertEqual(vf.PROMPT.count("hand_cream: a soft squeezable"), 1)
            self.assertTrue(vf.PROMPT.startswith(orig.rstrip("\n")))      # 원래 질문은 그대로, 뒤에만 붙음
            vf.PROMPT = orig
            from unittest import mock
            with mock.patch.dict(os.environ, {"TOWER_QWEN_HINT": "0"}):
                self.assertFalse(w.hint_prompt())
            self.assertEqual(vf.PROMPT, orig)
        finally:
            vf.PROMPT = orig

    def test_process_once_sends_size(self):
        from tools import intake_qwen_worker as w

        class Tower:
            def __init__(self):
                self.sent = []

            def pending(self):
                return [{"item_id": "A-20261111-0001", "photo_path": "photos/KIOSK-A/x.jpg"}]

            def send(self, iid, feats, cm=None, size=None):
                self.sent.append((iid, cm, size))
        t = Tower()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "photos/KIOSK-A").mkdir(parents=True)
            (Path(d) / "photos/KIOSK-A/x.jpg").write_bytes(b"x")
            n = w.process_once(t, lambda p: {"category": "lip_balm", "colors": []}, {}, log=lambda *a: None, root=Path(d),
                               measurer=lambda p, f: None, sizer=lambda p: {"found": True, "size_group": "핸드크림", "length": 380, "width": 127})
        self.assertEqual(n, 1)
        self.assertEqual(t.sent[0][2]["size_group"], "핸드크림")

    def test_color_uses_size_category(self):
        # 11/11 Qwen 이 크림을 립밤으로 읽어도 크기가 핸드크림이면 색은 핸드크림 규칙(하늘색·분홍 구별)으로 잰다
        from tools import intake_qwen_worker as w
        seen = []

        class Tower:
            def pending(self):
                return [{"item_id": "A-20261111-0002", "photo_path": "photos/KIOSK-A/y.jpg"}]

            def send(self, *a):
                pass
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "photos/KIOSK-A").mkdir(parents=True)
            (Path(d) / "photos/KIOSK-A/y.jpg").write_bytes(b"x")
            w.process_once(Tower(), lambda p: {"category": "lip_balm", "colors": []}, {}, log=lambda *a: None, root=Path(d),
                           measurer=lambda p, f: seen.append(f["category"]),
                           sizer=lambda p: {"found": True, "size_group": "핸드크림", "length": 380, "width": 127})
        self.assertEqual(seen, ["hand_cream"])


if __name__ == "__main__":
    unittest.main()
