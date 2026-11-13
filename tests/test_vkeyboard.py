"""11/10 화면 키보드(web/ui/vkeyboard.js) 시험 — 한글 두벌식 조합·지우기(node 가 있으면), 키오스크·폰 화면 연결"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JS = ROOT / "web" / "ui" / "vkeyboard.js"

CASES = [("ㅅㅓㅁㅕㄴㅇㅕㄱ", "서면역"), ("ㄱㅏㅂㅅ", "값"), ("ㄱㅏㅂㅅㅣ", "갑시"), ("ㅇㅗㅏ", "와"), ("ㄷㅗㅐㅈㅣ", "돼지"),
         ("ㅎㅐㅇㅜㄴㄷㅐ", "해운대"), ("ㅂㅕㄹ ㅅㅡㅌㅣㅋㅓ", "별 스티커"), ("ㅇㅣㄹㄱㅇㅓ", "읽어"), ("ㄲㅗㅊ", "꽃"),
         ("ㅎㅗㅇㄱㅣㄹㄷㅗㅇ", "홍길동"), ("ㄱㅏㄱ⌫", "가"), ("ㄱㅘ⌫", "고"), ("ㄱㅏㅂㅅ⌫⌫⌫", "ㄱ"), ("ㄸㅏㄸ", "따ㄸ")]

RUNNER = """
global.window = {}; require(process.argv[1]);
const {addJamo, backJamo} = window.VK._hangul;
const out = JSON.parse(process.argv[2]).map(seq => { let v = '', comp = false;
  for (const j of [...seq]) {
    if (j === '⌫') { if (comp && /[가-힣ㄱ-ㅣ]/.test(v.slice(-1))) { const b = backJamo(v.slice(-1)); v = v.slice(0, -1) + b; comp = !!b; } else v = v.slice(0, -1); continue; }
    if (j === ' ') { v += ' '; comp = false; continue; }
    const last = comp ? v.slice(-1) : ''; v = (comp ? v.slice(0, -1) : v) + addJamo(last, j); comp = true;
  } return v; });
console.log(JSON.stringify(out));
"""


class HangulTest(unittest.TestCase):
    def test_dubeolsik_compose_and_back(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 필요(한글 조합은 자바스크립트)")
        r = subprocess.run([node, "-e", RUNNER, str(JS), json.dumps([c[0] for c in CASES])], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), [c[1] for c in CASES])


class WiringTest(unittest.TestCase):
    def test_kiosk_uses_keyboard(self):
        html = (ROOT / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/ui/vkeyboard.js?v=20261112c"></script>', html)
        self.assertIn('<script src="/ui/phonefield.js?v=20261112a" defer></script>', html)
        self.assertIn('id="cphone"', html)
        self.assertIn('data-phone>', html)                          # 11/12 전화번호 세 칸

        self.assertIn("VK.attach(document, { skin: 'kiosk' })", html)
        self.assertIn('id="rid" data-vk="id"', html)              # 가린 신분증: 숫자 + * + -
        self.assertIn('id="rclaim" data-vk="en" data-vk-upper', html)

    def test_caret_editing_and_phone_field_1112(self):
        """11/12 바로 고치기: 커서 자리에 넣고 앞을 지움(맨 끝만 아님), 전화번호 세 칸·맨 앞 지우기로 앞 칸"""
        js = (ROOT / "web" / "ui" / "vkeyboard.js").read_text(encoding="utf-8")
        for needle in ("function sel()", "setSelectionRange", "vk-back-empty", "function drawCaret()", 'code === "ArrowLeft"'):
            self.assertIn(needle, js)
        pf = (ROOT / "web" / "ui" / "phonefield.js").read_text(encoding="utf-8")
        for needle in ("SIZES = [3, 4, 4]", "vk-back-empty", 'Object.defineProperty(orig, "value"'):
            self.assertIn(needle, pf)

    def test_phone_page_and_asset_served(self):
        try:
            from fastapi.testclient import TestClient
            from agents.api import build_app, build_service
        except ImportError:
            self.skipTest("fastapi 필요")
        c = TestClient(build_app(build_service()))
        r = c.get("/ui/vkeyboard.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["content-type"])
        p = c.get("/phone")
        self.assertEqual(p.status_code, 200)
        self.assertIn("VK.attach(frame.contentDocument", p.text)
        self.assertIn("/^\\/(?!\\/)/", p.text)                     # 같은 관제탑 주소만 틀 안에


    def test_field_stays_visible_and_esc_closes_1112(self):
        """11/12 교육원: 전화번호 칸이 키보드에 가려지고 닫은 뒤 흰 빈칸이 남음 · Esc 로 닫기
        (실제 화면 측정은 Playwright 로 함 — 여기서는 고친 자리가 남아 있는지만)"""
        js = (ROOT / "web" / "ui" / "vkeyboard.js").read_text(encoding="utf-8")
        self.assertIn("restorePads();\n        host.body.style.paddingBottom", js)       # 칸을 옮겨도 원래 여백 기록을 덮지 않음
        self.assertIn("box.getBoundingClientRect().bottom - kbTop()", js)               # 카드에는 넘친 만큼만
        self.assertIn("if (r.top - delta < top) delta = r.top - top;", js)                # 칸 위가 잘리지 않게
        self.assertIn('e.key === "Escape" && st.el', js)
        self.assertIn("escDocs.add(w.parent.document)", js)                              # 바깥 통합 화면에서도 Esc


if __name__ == "__main__":
    unittest.main()
