"""11/10 키오스크 자동 촬영 — 물건 감지 시험(web/kiosk/index.html 의 detect 구간을 node 로 실행)

배경: 교육원 실물 확인에서 휴대폰(검정)은 찍히는데 핸드크림(밝은 바닥 위의 작고 밝은 물건)은 못 잡았다.
손을 넣으면 잡히고 손을 빼면 '비어 있음'으로 돌아갔다. 원인은 화면 전체 평균으로만 견주던 기준(평균 차 14 이상) —
작은 물건은 평균에 묻힌다(실제 화면에서 잰 값: 핸드크림 2.2, 휴대폰 30.0).
고친 것: 색 차이가 큰 '뭉친' 픽셀의 넓이(화면의 1.4% 이상)도 물건으로 본다. 조명 변화·잡음·흩어진 점은 물건이 아니다.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")

RUNNER = r"""
const src = process.argv[1];
eval(src);                                        // diff · lightGain · changedArea · hasItem
const W = 64, H = 48, O = JSON.parse(process.argv[2]);
let seed = 12345; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const gauss = (s) => { let u = 0; for (let i = 0; i < 6; i++) u += rnd(); return (u - 3) * s * 1.41; };
// 밝은 바닥: 가운데는 밝고 가장자리는 어두움(카메라 렌즈 특성) + 옅은 보랏빛 + 잡음
function floor(noise) {
  const rgb = new Float32Array(W * H * 3);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const r2 = ((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2, v = 236 - 34 * r2, i = (y * W + x) * 3;
    rgb[i] = v * 0.97 + gauss(noise); rgb[i + 1] = v * 0.93 + gauss(noise); rgb[i + 2] = v + gauss(noise);
  }
  return rgb;
}
const clamp = (rgb) => { for (let i = 0; i < rgb.length; i++) rgb[i] = Math.max(0, Math.min(255, rgb[i])); return rgb; };
function frame(rgb) {                             // 화면의 small() 과 같은 모양: 흑백 배열 + .rgb
  clamp(rgb);
  const g = new Float32Array(W * H);
  for (let i = 0; i < g.length; i++) g[i] = (rgb[i*3] * 299 + rgb[i*3+1] * 587 + rgb[i*3+2] * 114) / 1000;
  g.rgb = rgb; return g;
}
function paint(rgb, x0, y0, w, h, fn) { for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) { const i = (y * W + x) * 3; fn(rgb, i, x, y); } return rgb; }
const scale = (rgb, kr, kg, kb) => { for (let i = 0; i < rgb.length; i += 3) { rgb[i] *= kr; rgb[i+1] *= kg; rgb[i+2] *= kb; } return rgb; };
// 핸드크림: 화면의 약 6%(9×20), 바닥보다 조금 어둡고 옅은 무늬 + 작은 어두운 뚜껑
const cream = (rgb) => { paint(rgb, 28, 14, 9, 20, (a, i, x, y) => { const p = ((x + y) % 3 === 0) ? -9 : 4; a[i] = a[i] * 0.90 + p; a[i+1] = a[i+1] * 0.92 + p; a[i+2] = a[i+2] * 0.90 + p; });
  return paint(rgb, 30, 34, 4, 3, (a, i) => { a[i] = 70; a[i+1] = 72; a[i+2] = 78; }); };
const phone = (rgb) => paint(rgb, 20, 14, 26, 18, (a, i) => { a[i] = 40; a[i+1] = 42; a[i+2] = 48; });
const base = frame(floor(1.5));
const mk = (fn) => frame(fn(floor(1.5)));
const scenes = {
  empty_again:    mk((r) => r),
  cream:          mk(cream),
  cream_dim:      mk((r) => scale(cream(r), 0.85, 0.85, 0.85)),
  phone:          mk(phone),
  light_down:     mk((r) => scale(r, 0.80, 0.80, 0.80)),
  light_up:       mk((r) => scale(r, 1.15, 1.15, 1.15)),          // 가운데가 하얗게 날아감
  white_balance:  mk((r) => scale(r, 1.06, 1.00, 0.93)),
  noisy:          frame(floor(6)),
  specks:         mk((r) => { for (let k = 0; k < 70; k++) { const i = Math.floor(rnd() * W * H) * 3; r[i] -= 90; r[i+1] -= 90; r[i+2] -= 90; } return r; }),
  thin_line:      mk((r) => paint(r, 10, 24, 44, 1, (a, i) => { a[i] -= 80; a[i+1] -= 80; a[i+2] -= 80; })),
  tiny_spot:      mk((r) => paint(r, 40, 30, 2, 2, (a, i) => { a[i] = 60; a[i+1] = 60; a[i+2] = 60; })),
};
const out = {};
for (const [k, f] of Object.entries(scenes)) out[k] = {item: hasItem(f, base, O), avg: +diff(f, base).toFixed(2), area: +changedArea(f.rgb, base.rgb, W, H, O.pix).toFixed(4)};
out.no_rgb = hasItem(Object.assign(new Float32Array(scenes.cream), {}), base, O);     // 색 배열이 없으면 예전 기준만(오류 없이)
console.log(JSON.stringify(out));
"""


def detect_source() -> str:
    m = re.search(r"// ---- detect:begin.*?\n(.*?)// ---- detect:end ----", HTML, re.S)
    assert m, "detect 구간 표시가 없습니다"
    return m.group(1)


def auto_options() -> dict:
    m = re.search(r"const AUTO = \{(.*?)\};", HTML, re.S)
    body = re.sub(r"\s+", " ", m.group(1))
    return {k: float(v) for k, v in re.findall(r"(\w+): ([\d.]+)", body)}


class DetectTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 필요(감지 계산은 자바스크립트)")
        cls.opt = auto_options()
        r = subprocess.run([node, "-e", RUNNER, detect_source(), json.dumps(cls.opt)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError(r.stderr[-2000:])
        cls.out = json.loads(r.stdout)

    def test_small_bright_item_is_found(self):
        cream = self.out["cream"]
        self.assertLess(cream["avg"], self.opt["changed"])            # 예전 기준(화면 전체 평균)으로는 못 잡는 물건
        self.assertTrue(cream["item"], cream)                          # 새 기준으로 잡힌다
        self.assertGreaterEqual(cream["area"], self.opt["area"] * 2)   # 기준의 두 배 이상 여유
        self.assertTrue(self.out["cream_dim"]["item"], self.out["cream_dim"])   # 놓는 순간 조명이 어두워져도

    def test_big_dark_item_still_found(self):
        self.assertTrue(self.out["phone"]["item"])
        self.assertGreaterEqual(self.out["phone"]["avg"], self.opt["changed"])

    def test_empty_box_is_not_an_item(self):
        for name in ("empty_again", "light_down", "light_up", "white_balance", "noisy", "specks", "thin_line", "tiny_spot"):
            with self.subTest(name):
                self.assertFalse(self.out[name]["item"], self.out[name])
                self.assertLess(self.out[name]["area"], self.opt["area"] / 2)   # 기준의 절반에도 못 미침

    def test_missing_color_array_falls_back(self):
        self.assertFalse(self.out["no_rgb"])


class WiringTest(unittest.TestCase):
    def test_tick_uses_new_check(self):
        self.assertIn("if (!hasItem(cur, empty, AUTO)) {", HTML)
        self.assertIn("!hasItem(cur, trueEmpty, AUTO)) empty = cur;", HTML)
        self.assertIn("out.rgb = rgb;", HTML)
        self.assertNotIn("diff(cur, empty)", HTML)                     # 예전 판단이 남아 있지 않다
        opt = auto_options()
        self.assertEqual((opt["pix"], opt["area"], opt["changed"]), (30.0, 0.014, 14.0))


if __name__ == "__main__":
    unittest.main()
