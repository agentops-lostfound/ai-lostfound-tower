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
        self.assertIn('<script src="/ui/vkeyboard.js?v=20261111a"></script>', html)
        self.assertIn("VK.attach(document, { skin: 'kiosk' })", html)
        self.assertIn('id="rid" data-vk="id"', html)              # 가린 신분증: 숫자 + * + -
        self.assertIn('id="rclaim" data-vk="en" data-vk-upper', html)

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


if __name__ == "__main__":
    unittest.main()
