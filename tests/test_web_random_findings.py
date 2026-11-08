"""11/8 웹 화면 무작위 시험(Playwright 3크기 + 무작위 클릭)에서 찾은 허점 — 다시 생기지 않게"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.chat_rag import GroundedRag  # noqa: E402
from agents.guidance import Guidance  # noqa: E402
from agents.tower_brain import DEFAULT_REASON, clean_reason  # noqa: E402


def page(name):
    return (ROOT / "web" / name / "index.html").read_text(encoding="utf-8")


class WebPageTest(unittest.TestCase):
    def test_lost_page_blocks_phone_without_hyphen_and_keeps_other_color(self):
        s = page("lost")
        self.assertIn(r"\d{2,4}-?\d{3,4}-?\d{4}", s)               # 01012345678 도 막음(키오스크와 같은 규칙)
        self.assertNotIn("'보라' : ''", s)                         # '기타' 색을 '보라'로 바꿔 보내지 않음

    def test_phone_width_layouts(self):
        self.assertIn("flex-wrap:wrap", page("admin"))           # 제목이 한 글자씩 세로로 눌리지 않게
        s = page("storage-desk")
        self.assertGreater(s.index("max-width:600px"), s.index(".boardwrap {"))   # 휴대폰 규칙이 기본 규칙보다 뒤(이겨야 함)

    def test_kiosk_place_checked_at_step2_and_field_name_hidden(self):
        s = page("kiosk")
        self.assertIn("id=\"perr\"", s)
        self.assertIn("if (PII.test(place))", s)
        self.assertNotIn("물건 잃어버렸어요</b>에서 먼저 접수", s)   # 저장 안 되는 탭으로 보내지 않음

    def test_live_lists_blur_tag(self):
        self.assertIn("#흐린촬영", page("live"))


class ServerSideTest(unittest.TestCase):
    def test_sim_lost_rejects_pii(self):
        from agents.sim_director import RequestError, SimDirector
        d = SimDirector.__new__(SimDirector)
        with self.assertRaises(RequestError):
            SimDirector.lost(d, "검정 지갑 잃어버렸어요 연락처 01012345678")

    def test_chat_garbage_is_not_called_english(self):
        a = GroundedRag(Guidance(), None)
        for q in ("ㅁㄴㅇㄹ ;;; DROP TABLE users", "<script>alert(1)</script>"):
            self.assertNotIn("한국어 안내만", a.ask(q)["answer"], q)
        self.assertIn("한국어 안내만", a.ask("How do I find my lost wallet?")["answer"])

    def test_brain_reason_not_copied_from_other_agent_example(self):
        ex = "두 후보 점수가 같아서 보관 칸 기록으로 좁히려고"
        self.assertEqual(clean_reason("matching_agent", ex), DEFAULT_REASON["matching_agent"])
        self.assertEqual(clean_reason("storage_agent", ex), ex)
        ok = "특징이 비슷한 후보가 둘이라서 차이를 보려고"
        self.assertEqual(clean_reason("matching_agent", ok), ok)


if __name__ == "__main__":
    unittest.main()
