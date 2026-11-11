"""11/11 키오스크 사진 색 측정(agents/color_measure.py) 시험 — 회색 펠트 기준 색 판정·확실할 때만 Qwen 색 바꾸기·작업자·저장 연결

실제 11/11 사진(펠트 20장)은 저장소에 넣지 않으므로(jpg 제외), 그 사진에서 잰 특징을 흉내 낸 그림으로 시험한다:
펠트 잔무늬(무늬 세기 약 10) · 렌즈 가장자리가 어두움(주변부 감광) · 카메라가 연보라로 치우침(R156·G146·B168)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from agents import color_measure as cmz  # noqa: E402

CAST = np.array([1.04, 0.97, 1.12], np.float32)     # 연보라 치우침(R,G,B)


def scene(path, obj_rel=None, box=(100, 60, 140, 120), felt=True, clip_obj=False, corner=False, seed=0):
    """240×180 사진: 바닥 150(회색) × 치우침 × 주변부 감광 + 펠트 잔무늬, 물건 = 바닥 대비 색(obj_rel)"""
    rng = np.random.default_rng(seed)
    h, w = 180, 240
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2
    light = (1 - 0.18 * r2)[..., None] * CAST
    base = np.ones((h, w, 3), np.float32)
    if felt:
        base *= 1 + rng.normal(0, 0.015, (h, w, 1))
    if obj_rel is not None:
        x0, y0, x1, y1 = box
        base[y0:y1, x0:x1] = np.array(obj_rel, np.float32)
    img = 150 * base * light
    if obj_rel is not None and clip_obj:
        x0, y0, x1, y1 = box
        img[y0:y1, x0:x1] = 252                             # 하얗게 날아감
    if corner:
        img[150:, :30] = [170, 180, 230]                    # 왼쪽 아래 모서리 반사(11/11 134001 사진)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path, quality=95)
    return path


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def m(self, name, cat=None, **kw):
        return cmz.measure(scene(self.d / f"{name}.jpg", **kw), cat)

    def test_colors_on_felt(self):
        cases = [("red", (1.0, 0.68, 0.72), "빨강"), ("blue", (0.68, 0.78, 1.08), "파랑"),          # 11/11 립밤 실측(채도 약 30%)에 맞춤
                 ("black", (0.6, 0.6, 0.6), "검정"), ("white", (1.4, 1.4, 1.4), "흰색"), ("green", (0.75, 1.0, 0.75), "초록")]
        for name, rel, want in cases:
            with self.subTest(name):
                r = self.m(name, obj_rel=rel)
                self.assertTrue(r["found"])
                self.assertEqual(r["color"], want, r)
                self.assertTrue(r["sure"], r)
                self.assertGreater(r["texture"], cmz.FELT_TEXTURE)

    def test_cast_is_removed(self):
        """연보라 치우침 아래의 회색에 가까운 흰 물건이 파랑·보라로 나오지 않음(바닥으로 나눔)"""
        r = self.m("white2", obj_rel=(1.3, 1.3, 1.3))
        self.assertEqual(r["color"], "흰색")
        self.assertLess(r["sat"], 0.06)

    def test_clipped_pastel_cream_is_not_sure(self):
        """다 날아간 연한 크림은 흰색으로 단정하지 않음(Qwen 색 유지). 폰이면 흰색 확실"""
        cream = self.m("cream", "핸드크림", obj_rel=(1.3, 1.25, 1.3), clip_obj=True)
        self.assertEqual(cream["color"], "흰색")
        self.assertFalse(cream["sure"])
        self.assertIn("날아간", cream["reason"])
        self.assertEqual(cream["sat"], 0.0)                 # 날아간 점으로 없던 색을 만들지 않음
        phone = self.m("phone", "모형폰", obj_rel=(1.3, 1.25, 1.3), clip_obj=True)
        self.assertEqual(phone["color"], "흰색")
        self.assertTrue(phone["sure"])

    def test_smooth_floor_is_refused(self):
        """도화지·종이처럼 잔무늬가 없는 바닥은 회색 기준이 아니므로 재지 않음"""
        r = self.m("paper", obj_rel=(1.05, 0.45, 0.5), felt=False)
        self.assertFalse(r["found"])
        self.assertIsNone(r["color"])
        self.assertIn("펠트가 아님", r["reason"])

    def test_empty_box(self):
        r = self.m("empty")
        self.assertFalse(r["found"])
        self.assertFalse(r["sure"])

    def test_corner_glare_is_not_the_object(self):
        r = self.m("corner", obj_rel=(0.45, 0.6, 1.2), corner=True)
        self.assertEqual(r["color"], "파랑")
        self.assertLess(r["area"], 0.1)

    def test_big_object_in_cropped_photo(self):
        """키오스크가 잘라 키운 사진: 물건이 화면의 약 40% — 바닥 곡면은 바깥 띠에서 맞춤"""
        r = self.m("crop", obj_rel=(1.05, 0.45, 0.5), box=(55, 35, 185, 145))
        self.assertEqual(r["color"], "빨강")
        self.assertTrue(r["sure"])


class DecideTest(unittest.TestCase):
    def test_only_sure_measure_changes_color(self):
        feats = {"category": "립밤", "color": "갈색", "shape": "tube"}
        self.assertEqual(cmz.apply_to_features(feats, {"color": "빨강", "sure": True})["color"], "빨강")
        self.assertEqual(cmz.apply_to_features(feats, {"color": "빨강", "sure": False})["color"], "갈색")
        self.assertEqual(cmz.apply_to_features(feats, {"color": "보라", "sure": True})["color"], "갈색")     # 계약에 없는 색
        self.assertEqual(cmz.apply_to_features(feats, {"color": "빨강", "sure": "yes"})["color"], "갈색")   # True 만
        self.assertEqual(cmz.apply_to_features(feats, None), feats)
        self.assertEqual(cmz.apply_to_features(feats, "빨강"), feats)

    def test_view_and_decide(self):
        v = cmz.view({"color": "빨강", "sure": True, "reason": "유채색"}, "갈색")
        self.assertEqual((v["qwen"], v["measured"], v["used"]), ("갈색", "빨강", "빨강"))
        self.assertIn("바꿈", v["why"])
        v = cmz.view({"color": "흰색", "sure": False, "reason": "날아감"}, "분홍")
        self.assertEqual(v["used"], "분홍")
        self.assertIn("유지", v["why"])
        self.assertEqual(cmz.decide("빨강", {"color": "빨강", "sure": True})[1], "Qwen·색 측정 같음")
        self.assertIsNone(cmz.view(None, "빨강"))

    def test_summary_keeps_numbers_only(self):
        s = cmz.summary({"found": True, "color": "파랑", "sure": True, "reason": "x", "lum": 0.8, "extra": [1, 2]})
        self.assertNotIn("extra", s)
        self.assertIsNone(cmz.summary(None))


class IntakeTest(unittest.TestCase):
    QWEN = {"category": "lip_balm", "colors": ["brown"], "shape": "stick", "materials": ["plastic"],
            "logos_or_text": [], "sticker_status": "absent", "stickers": [], "distinctive_features": []}

    def test_parse_features_uses_sure_measure(self):
        from agents.intake import IntakeError, parse_features
        self.assertEqual(parse_features({"qwen": self.QWEN})["color"], "갈색")
        f = parse_features({"qwen": self.QWEN, "confidence": 0.85, "color_measure": {"color": "빨강", "sure": True}})
        self.assertEqual(f["color"], "빨강")
        self.assertEqual(f["category"], "립밤")
        f = parse_features({"qwen": self.QWEN, "color_measure": {"color": "빨강", "sure": False}})
        self.assertEqual(f["color"], "갈색")
        with self.assertRaises(IntakeError):
            parse_features({"qwen": self.QWEN, "color_measure": "빨강"})
        with self.assertRaises(IntakeError):
            parse_features({"qwen": self.QWEN, "other": 1})

    def test_vision_event_shows_measure(self):
        from agents.vision_watch import VisionWatch

        class Board:
            def __init__(self):
                self.ev = []

            def vision(self, d):
                self.ev.append(d)
        b = Board()
        VisionWatch(b).result("A-20261111-0001", self.QWEN, {"category": "립밤", "color": "빨강"},
                              measure=cmz.view({"color": "빨강", "sure": True, "reason": "유채색"}, "갈색"))
        m = b.ev[-1]["measure"]
        self.assertEqual((m["qwen"], m["measured"], m["used"]), ("갈색", "빨강", "빨강"))
        VisionWatch(b).result("A-20261111-0002", self.QWEN, {"category": "립밤", "color": "갈색"})
        self.assertNotIn("measure", b.ev[-1])


class WorkerTest(unittest.TestCase):
    def test_worker_sends_measure_and_survives_failure(self):
        from tools import intake_qwen_worker as worker

        class Tower:
            def __init__(self):
                self.sent = []

            def pending(self):
                return [{"item_id": "A-20261111-0001", "photo_path": "photos/a.jpg"}]

            def send(self, iid, feats, cm=None):
                self.sent.append((iid, feats, cm))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "photos").mkdir()
            scene(root / "photos" / "a.jpg", obj_rel=(1.05, 0.45, 0.5))
            t, logs = Tower(), []
            q = IntakeTest.QWEN
            self.assertEqual(worker.process_once(t, lambda p: q, {}, logs.append, root), 1)
            cm = t.sent[-1][2]
            self.assertEqual((cm["color"], cm["sure"]), ("빨강", True))       # 진짜 측정기로 잼
            self.assertIn("색 측정 빨강(확실)", logs[-1])

            t2 = Tower()
            self.assertEqual(worker.process_once(t2, lambda p: q, {}, logs.append, root,
                                                 measurer=lambda p, f: worker.measure_color(Path("/없는/사진.jpg"), f)), 1)
            self.assertIsNone(t2.sent[-1][2])                                  # 측정이 안 돼도 Qwen 결과는 보냄
            old = os.environ.get("TOWER_COLOR_MEASURE")
            os.environ["TOWER_COLOR_MEASURE"] = "0"
            try:
                self.assertIsNone(worker.measure_color(root / "photos" / "a.jpg", q))
            finally:
                if old is None:
                    os.environ.pop("TOWER_COLOR_MEASURE", None)
                else:
                    os.environ["TOWER_COLOR_MEASURE"] = old


class ShowcaseTest(unittest.TestCase):
    def test_card_has_measure_line(self):
        html = (Path(__file__).resolve().parent.parent / "web" / "showcase" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function measureLine", html)
        self.assertIn("v.measure = d.measure", html)


if __name__ == "__main__":
    unittest.main()
