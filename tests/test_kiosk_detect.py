"""11/10 키오스크 자동 촬영 — 물건 감지 시험(web/kiosk/index.html 의 detect 구간을 node 로 실행)

배경: 교육원 실물 확인에서 휴대폰(검정)은 찍히는데 핸드크림(밝은 바닥 위의 작고 밝은 물건)은 못 잡았다.
손을 넣으면 잡히고 손을 빼면 '비어 있음'으로 돌아갔다. 원인은 화면 전체 평균으로만 견주던 기준(평균 차 14 이상) —
작은 물건은 평균에 묻힌다(실제 화면에서 잰 값: 핸드크림 2.2, 휴대폰 30.0).
고친 것: 색 차이가 큰 '뭉친' 픽셀의 넓이도 물건으로 본다. 조명 변화·잡음·흩어진 점은 물건이 아니다.
11/10 오후: 포토박스 안쪽이 반짝이는 은박이라 화면마다 픽셀이 크게 흔들렸다 → 최근 네 장 평균 화면으로 견주고,
픽셀 기준은 지금 잡음 수준 아래로 내려가지 않게 한다(잰 값: 화면 한 장끼리 상위 5% 픽셀 차 27, 네 장 평균끼리 14).
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
eval(src);                                        // diff · lightGain · changedArea · meanFrames · pixP95 · pixLimit · hasItem
const W = 64, H = 48, O = JSON.parse(process.argv[2]);
let seed = 12345; const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const gauss = (s) => { let u = 0; for (let i = 0; i < 6; i++) u += rnd(); return (u - 3) * s * 1.41; };
// 밝은 바닥: 가운데는 밝고 가장자리는 어두움(카메라 렌즈 특성) + 옅은 보랏빛 + 잡음(noise: 화면마다 달라지는 흔들림)
function floor(noise) {
  const rgb = new Float32Array(W * H * 3);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const r2 = ((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2, v = 236 - 34 * r2, i = (y * W + x) * 3;
    rgb[i] = v * 0.97 + gauss(noise); rgb[i + 1] = v * 0.93 + gauss(noise); rgb[i + 2] = v + gauss(noise);
  }
  return rgb;
}
const clamp = (rgb) => { for (let i = 0; i < rgb.length; i++) rgb[i] = Math.max(0, Math.min(255, rgb[i])); return rgb; };
function gray(rgb) { const g = new Float32Array(W * H); for (let i = 0; i < g.length; i++) g[i] = (rgb[i*3] * 299 + rgb[i*3+1] * 587 + rgb[i*3+2] * 114) / 1000; return g; }
// 화면의 tick 과 같은 모양: 최근 avgN 장을 찍어 마지막 장의 흑백 + 색(.rgb) + 평균 화면(.avg)
function shot(fn, noise) {
  const frames = []; for (let k = 0; k < O.avgN; k++) frames.push(clamp(fn(floor(noise))));
  const g = gray(frames[frames.length - 1]); g.rgb = frames[frames.length - 1]; g.avg = meanFrames(frames); return g;
}
function paint(rgb, x0, y0, w, h, fn) { for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) { const i = (y * W + x) * 3; fn(rgb, i, x, y); } return rgb; }
const scale = (rgb, kr, kg, kb) => { for (let i = 0; i < rgb.length; i += 3) { rgb[i] *= kr; rgb[i+1] *= kg; rgb[i+2] *= kb; } return rgb; };
// 핸드크림: 화면의 약 6%(9×20), 바닥보다 조금 어둡고 옅은 무늬 + 작은 어두운 뚜껑. k = 몸통 밝기 비율(1 에 가까울수록 바닥과 비슷)
const cream = (k) => (rgb) => { paint(rgb, 28, 14, 9, 20, (a, i, x, y) => { const p = ((x + y) % 3 === 0) ? -9 : 4; a[i] = a[i] * k + p; a[i+1] = a[i+1] * (k + 0.02) + p; a[i+2] = a[i+2] * k + p; });
  return paint(rgb, 30, 34, 4, 3, (a, i) => { a[i] = 70; a[i+1] = 72; a[i+2] = 78; }); };
const phone = (rgb) => paint(rgb, 20, 14, 26, 18, (a, i) => { a[i] = 40; a[i+1] = 42; a[i+2] = 48; });
const same = (r) => r;
const QUIET = 1.5, FOIL = 5.5;                      // 잡음: 보통 바닥 · 은박 바닥(교육원에서 잰 값과 비슷하게 — 화면 한 장끼리 상위 5% 픽셀 차 약 27)
function run(noise) {
  const base = shot(same, noise), out = {};
  const noises = []; let prev = shot(same, noise);
  for (let k = 0; k < 8; k++) { const cur = shot(same, noise); noises.push(pixP95(cur.avg, prev.avg)); prev = cur; }
  const o = Object.assign({}, O, {pixNow: pixLimit(noises, O)});
  const scenes = {
    empty_again: shot(same, noise), cream: shot(cream(0.90), noise), cream_dim: shot((r) => scale(cream(0.90)(r), 0.85, 0.85, 0.85), noise),
    phone: shot(phone, noise), light_down: shot((r) => scale(r, 0.80, 0.80, 0.80), noise), light_up: shot((r) => scale(r, 1.15, 1.15, 1.15), noise),
    white_balance: shot((r) => scale(r, 1.06, 1.00, 0.93), noise),
    specks: shot((r) => { for (let k = 0; k < 70; k++) { const i = Math.floor(rnd() * W * H) * 3; r[i] -= 90; r[i+1] -= 90; r[i+2] -= 90; } return r; }, noise),
    thin_line: shot((r) => paint(r, 10, 24, 44, 1, (a, i) => { a[i] -= 80; a[i+1] -= 80; a[i+2] -= 80; }), noise),
    tiny_spot: shot((r) => paint(r, 40, 30, 2, 2, (a, i) => { a[i] = 60; a[i+1] = 60; a[i+2] = 60; }), noise),
  };
  for (const [k, f] of Object.entries(scenes)) out[k] = {item: hasItem(f, base, o), avg: +diff(f, base).toFixed(2), area: +changedArea(f.avg, base.avg, W, H, o.pixNow).toFixed(4)};
  out.pixNow = +o.pixNow.toFixed(1); out.noise = +noises.slice().sort((x, y) => x - y)[noises.length >> 1].toFixed(1);
  const one = (fn) => { const r = clamp(fn(floor(noise))); const g = gray(r); g.rgb = r; return g; };
  out.single_pair_p95 = +pixP95(one(same).rgb, one(same).rgb).toFixed(1);                 // 화면 한 장끼리(평균 안 함)
  return out;
}
const out = {quiet: run(QUIET), foil: run(FOIL)};
const plain = (fn) => { const r = clamp(fn(floor(QUIET))); const g = gray(r); g.rgb = r; return g; };   // 평균 화면 없이(.avg 없음)도 돈다
out.no_avg = hasItem(plain(phone), plain(same), O);
out.no_rgb = hasItem(gray(clamp(cream(0.90)(floor(QUIET)))), gray(floor(QUIET)), O);                    // 색 배열도 없으면 예전 기준만
out.limit_few = pixLimit([40, 40, 40], O); out.limit_loud = pixLimit([30, 30, 30, 30, 30, 30], O);
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
    EMPTY = ("empty_again", "light_down", "light_up", "white_balance", "specks", "thin_line", "tiny_spot")

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
        cream = self.out["quiet"]["cream"]
        self.assertLess(cream["avg"], self.opt["changed"])            # 예전 기준(화면 전체 평균)으로는 못 잡는 물건
        self.assertTrue(cream["item"], cream)                          # 새 기준으로 잡힌다
        self.assertGreaterEqual(cream["area"], self.opt["area"] * 2)   # 기준의 두 배 이상 여유
        self.assertTrue(self.out["quiet"]["cream_dim"]["item"])        # 놓는 순간 조명이 어두워져도

    def test_big_dark_item_still_found(self):
        for floor in ("quiet", "foil"):
            self.assertTrue(self.out[floor]["phone"]["item"])
            self.assertGreaterEqual(self.out[floor]["phone"]["avg"], self.opt["changed"])

    def test_empty_box_is_not_an_item(self):
        for floor in ("quiet", "foil"):
            for name in self.EMPTY:
                with self.subTest(floor=floor, scene=name):
                    self.assertFalse(self.out[floor][name]["item"], self.out[floor][name])
                    self.assertLess(self.out[floor][name]["area"], self.opt["area"] / 2)   # 기준의 절반에도 못 미침

    def test_glittering_foil_floor(self):
        """11/10 포토박스 은박 바닥: 화면마다 반짝임이 달라 픽셀이 크게 흔들려도 빈 상자를 물건으로 보지 않고, 작은 물건은 잡는다"""
        foil = self.out["foil"]
        self.assertGreater(foil["single_pair_p95"], 20)                # 화면 한 장끼리는 기본 픽셀 기준(22)에 닿을 만큼 흔들림
        self.assertLess(foil["noise"], foil["single_pair_p95"] * 0.7)  # 네 장 평균끼리는 훨씬 잔잔하다
        self.assertGreaterEqual(foil["pixNow"], self.opt["pix"])
        self.assertTrue(foil["cream"]["item"], foil["cream"])
        self.assertTrue(foil["cream_dim"]["item"], foil["cream_dim"])

    def test_pixel_limit_follows_noise(self):
        self.assertEqual(self.out["limit_few"], self.opt["pix"])        # 잡음 기록이 모이기 전에는 기본값
        self.assertEqual(self.out["limit_loud"], 30 * self.opt["noiseK"])   # 잡음이 크면 그 위로 올린다
        self.assertEqual(self.out["quiet"]["pixNow"], self.opt["pix"])  # 잔잔한 바닥은 기본값 그대로

    def test_missing_arrays_fall_back(self):
        self.assertTrue(self.out["no_avg"])                             # 평균 화면이 없으면 화면 한 장으로
        self.assertFalse(self.out["no_rgb"])                            # 색 배열도 없으면 예전 기준만(오류 없이)


class WiringTest(unittest.TestCase):
    def test_tick_uses_new_check(self):
        self.assertIn("if (!hasItem(cur, empty, AUTO)) {", HTML)
        self.assertIn("!hasItem(cur, trueEmpty, AUTO)) empty = cur;", HTML)
        self.assertIn("out.rgb = rgb;", HTML)
        self.assertNotIn("diff(cur, empty)", HTML)                     # 예전 판단이 남아 있지 않다
        opt = auto_options()
        self.assertEqual((opt["pix"], opt["area"], opt["changed"], opt["avgN"], opt["noiseK"]), (22.0, 0.012, 14.0, 4.0, 1.5))
        for needle in ("cur.avg = meanFrames(rgbHist);", "AUTO.pixNow = pixLimit(pixNoise, AUTO);",
                       "if (START_TAB) tab(START_TAB); else startCam();"):
            self.assertIn(needle, HTML)


if __name__ == "__main__":
    unittest.main()
