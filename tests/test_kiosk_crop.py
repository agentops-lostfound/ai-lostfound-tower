"""11/11 키오스크 촬영: 물건 둘레만 잘라 Qwen 에 보내기(web/kiosk/index.html detect 구간의 changedBox · cropRect)

배경: 포토박스 바닥에 둔 립밤은 화면의 몇 %라 Qwen 이 줄인 사진에서 글자·색을 못 읽고 JSON 검증 실패(RuntimeError)가 났다.
손으로 카메라에 가까이 대면 '파란 립밤'으로 읽었다 → 빈 상자와 달라진 곳(물건)만 잘라 보낸다. 큰 물건·감지 실패는 전체 사진 그대로.
"""
import json
import shutil
import subprocess
import unittest

from tests.test_kiosk_detect import detect_source, auto_options

RUNNER = r"""
eval(process.argv[1]);
const W = 64, H = 48, O = JSON.parse(process.argv[2]);
let seed = 777; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const gauss = (s) => { let u = 0; for (let i = 0; i < 6; i++) u += rnd(); return (u - 3) * s * 1.41; };
function floor(noise) { const r = new Float32Array(W * H * 3);
  for (let i = 0; i < r.length; i += 3) { r[i] = 200 + gauss(noise); r[i+1] = 190 + gauss(noise); r[i+2] = 215 + gauss(noise); } return r; }
function paint(r, x0, y0, w, h, rgb) { for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) { const i = (y * W + x) * 3; r[i] = rgb[0]; r[i+1] = rgb[1]; r[i+2] = rgb[2]; } return r; }
const base = floor(2), FW = 960, FH = 720, out = {};
// 립밤: 작은 세로 막대(3×9 칸 = 화면 약 0.9%), 오른쪽 아래쯤
const lip = paint(floor(2), 44, 30, 3, 9, [40, 70, 190]);
out.lip_box = changedBox(lip, base, W, H, O.pix);
out.lip_crop = cropRect(out.lip_box, W, H, FW, FH);
// 휴대폰: 화면 절반 가까이 → 자르지 않음
const phone = paint(floor(2), 8, 6, 46, 34, [30, 30, 35]);
out.phone_crop = cropRect(changedBox(phone, base, W, H, O.pix), W, H, FW, FH);
// 반짝임 몇 점만(물건 없음) → 범위 없음
const specks = floor(2); for (let k = 0; k < 5; k++) paint(specks, Math.floor(rnd() * 60), Math.floor(rnd() * 44), 1, 1, [255, 255, 255]);
out.specks = changedBox(specks, base, W, H, O.pix);
// 립밤 + 멀리 떨어진 반짝임 한 점 → 범위가 끌려가지 않음
const lip2 = paint(paint(floor(2), 44, 30, 3, 9, [40, 70, 190]), 2, 2, 2, 2, [255, 255, 255]);
out.lip2_crop = cropRect(changedBox(lip2, base, W, H, O.pix), W, H, FW, FH);
out.none = cropRect(null, W, H, FW, FH);
console.log(JSON.stringify(out));
"""


class CropTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 필요")
        r = subprocess.run([node, "-e", RUNNER, detect_source(), json.dumps(auto_options())], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr[-2000:])
        cls.out = json.loads(r.stdout)

    def test_small_item_is_cropped_around_it(self):
        b, c = self.out["lip_box"], self.out["lip_crop"]
        self.assertEqual((b["x0"], b["y0"], b["x1"], b["y1"]), (44, 30, 47, 39))
        self.assertIsNotNone(c)
        cx, cy = 45.5 * 960 / 64, 34.5 * 720 / 48                    # 립밤 가운데(원본 픽셀)
        self.assertTrue(c["x"] < cx < c["x"] + c["w"] and c["y"] < cy < c["y"] + c["h"], c)
        self.assertLess(c["w"] * c["h"], 960 * 720 * 0.25)             # 원본의 1/4 보다 작게 → 물건이 크게 보임
        self.assertGreaterEqual(min(c["w"], c["h"]), round(720 * 0.3) - 1)   # 너무 작게 자르지 않음(둘레를 남김)
        self.assertTrue(c["x"] >= 0 and c["y"] >= 0 and c["x"] + c["w"] <= 960 and c["y"] + c["h"] <= 720)

    def test_big_item_and_no_item_keep_full_photo(self):
        self.assertIsNone(self.out["phone_crop"])
        self.assertIsNone(self.out["specks"])
        self.assertIsNone(self.out["none"])

    def test_one_far_glint_does_not_stretch_crop(self):
        self.assertEqual(self.out["lip2_crop"], self.out["lip_crop"])

    def test_capture_uses_crop(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        self.assertIn("r = cropRect(changedBox(cur.avg || cur.rgb, base.avg || base.rgb, AUTO.w, AUTO.h, AUTO.pixNow || AUTO.pix), AUTO.w, AUTO.h, W, H);", html)


if __name__ == "__main__":
    unittest.main()
