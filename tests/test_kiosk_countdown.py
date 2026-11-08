"""11/9 키오스크 카운트다운(10초, 9초 …) 창 크기 고정 — 사용자 화면: 매 초 문장 간격·창 크기가 바뀌어 어지러움
실제 크기 측정(Playwright, 매 초 getBoundingClientRect 폭·높이 변화 0)은 손 확인. 여기서는 그 조건이 되는 표시 규칙을 고정한다"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(ROOT, "web/kiosk/index.html"), encoding="utf-8").read()


class KioskCountdownTest(unittest.TestCase):
    def test_number_box_has_fixed_width_digits(self):
        rule = re.search(r"\.cdnum\{([^}]*)\}", HTML)
        self.assertIsNotNone(rule)
        self.assertIn("font-variant-numeric:tabular-nums", rule.group(1))
        self.assertIn("min-width:2ch", rule.group(1))
        self.assertIn("display:inline-block", rule.group(1))

    def test_both_countdowns_use_fixed_number_box(self):
        self.assertRegex(HTML, r'class="cdnum" id="idleCount"')
        self.assertRegex(HTML, r'class="cdnum" id="count"')

    def test_idle_sentence_breaks_at_fixed_place(self):
        # 무조작 확인 창: 문장을 줄마다 나눠 숫자가 바뀌어도 줄바꿈 자리가 같게
        self.assertRegex(HTML, r'<p class="sub idle-msg"><span class="line"><b class="cdnum" id="idleCount">10</b>초 뒤 처음 화면으로 돌아가요\.</span> <span class="line">적은 내용은 지워져요\.</span></p>')
        self.assertIn(".idle-msg .line{display:block}", HTML)
        self.assertRegex(HTML, r"\.idle-card\{[^}]*width:min\(560px,100%\)")


if __name__ == "__main__":
    unittest.main()
