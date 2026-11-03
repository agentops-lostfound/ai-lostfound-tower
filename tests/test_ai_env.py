"""tools/check_ai_env.py 시험 — 실제 Ollama·GPU·.env 없이 가짜 입력으로 판정만 확인."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import check_ai_env as ce  # noqa: E402

FULL = {"DISCORD_WEBHOOK_PROGRESS": "https://x/1", "DISCORD_WEBHOOK_ALERT": "https://x/2",
        "DISCORD_WEBHOOK_SCORE": "https://x/3", "MAIN_AI_MODEL": "qwen3-vl:4b-instruct"}


def levels(checks):
    return {c.name: c.level for c in checks}


class TestPython(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(ce.check_python((3, 11, 0)).level, ce.OK)
        self.assertEqual(ce.check_python((3, 12, 4)).level, ce.OK)
        self.assertEqual(ce.check_python((3, 10, 9)).level, ce.FAIL)


class TestPackages(unittest.TestCase):
    def test_missing_is_warn_not_fail(self):
        def imp(name):
            if name == "mcp":
                raise ImportError
            return type("M", (), {"__version__": "1.0"})
        lv = levels(ce.check_packages(imp))
        self.assertEqual(lv["패키지 mcp"], ce.WARN)
        self.assertEqual(lv["패키지 langgraph"], ce.OK)


class TestEnv(unittest.TestCase):
    def test_full(self):
        lv = levels(ce.check_env(FULL, True))
        self.assertEqual(lv, {".env 파일": ce.OK, "디스코드 웹후크": ce.OK, "MAIN_AI_MODEL": ce.OK})

    def test_no_file_and_empty(self):
        lv = levels(ce.check_env({}, False))
        self.assertEqual(lv[".env 파일"], ce.FAIL)
        self.assertEqual(lv["디스코드 웹후크"], ce.WARN)
        self.assertEqual(lv["MAIN_AI_MODEL"], ce.WARN)

    def test_fallback_webhook_lists_missing(self):
        env = {"DISCORD_WEBHOOK_URL": "https://x/0", "DISCORD_WEBHOOK_SCORE": "https://x/3"}
        c = [c for c in ce.check_env(env, True) if c.name == "디스코드 웹후크"][0]
        self.assertEqual(c.level, ce.WARN)
        self.assertIn("progress", c.detail)
        self.assertNotIn("score", c.detail)

    def test_thinking_model_is_fail(self):
        lv = levels(ce.check_env({**FULL, "MAIN_AI_MODEL": "qwen3-vl:4b"}, True))
        self.assertEqual(lv["MAIN_AI_MODEL"], ce.FAIL)

    def test_blank_values_count_as_empty(self):
        lv = levels(ce.check_env({k: "  " for k in FULL}, True))
        self.assertEqual(lv["디스코드 웹후크"], ce.WARN)

    def test_secrets_never_printed(self):
        text = "\n".join(c.line() for c in ce.check_env(FULL, True))
        self.assertNotIn("https://", text)


class TestOllama(unittest.TestCase):
    def test_model_present(self):
        fetch = lambda url: {"models": [{"name": "qwen3-vl:4b-instruct"}, {"name": "mistral:latest"}]}
        lv = levels(ce.check_ollama("http://localhost:11434", "qwen3-vl:4b-instruct", fetch))
        self.assertEqual(lv, {"Ollama": ce.OK, "메인 AI 모델": ce.OK})

    def test_model_missing(self):
        fetch = lambda url: {"models": [{"name": "mistral:latest"}]}
        lv = levels(ce.check_ollama("u", "qwen3-vl:4b-instruct", fetch))
        self.assertEqual(lv["메인 AI 모델"], ce.FAIL)

    def test_tagless_name_means_latest(self):
        fetch = lambda url: {"models": [{"name": "mistral:latest"}]}
        lv = levels(ce.check_ollama("u", "mistral", fetch))
        self.assertEqual(lv["메인 AI 모델"], ce.OK)

    def test_not_running_is_warn(self):
        def fetch(url):
            raise ConnectionRefusedError
        checks = ce.check_ollama("u", "m", fetch)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].level, ce.WARN)

    def test_empty_model_list(self):
        lv = levels(ce.check_ollama("u", "qwen3-vl:4b-instruct", lambda url: {}))
        self.assertEqual(lv["메인 AI 모델"], ce.FAIL)


class TestGpu(unittest.TestCase):
    def test_enough_memory(self):
        c = ce.check_gpu(lambda cmd: "NVIDIA GeForce RTX 3050, 6144, 600\n")
        self.assertEqual(c.level, ce.OK)
        self.assertIn("5.4GB", c.detail)

    def test_low_memory_warns(self):
        c = ce.check_gpu(lambda cmd: "RTX 3050, 6144, 4000\n")
        self.assertEqual(c.level, ce.WARN)

    def test_bad_output(self):
        self.assertEqual(ce.check_gpu(lambda cmd: "").level, ce.WARN)


class TestDbPort(unittest.TestCase):
    def test_open_and_closed(self):
        class Sock:
            def close(self):
                pass
        self.assertEqual(ce.check_db_port(opener=lambda: Sock()).level, ce.OK)

        def refuse():
            raise ConnectionRefusedError
        c = ce.check_db_port(opener=refuse)
        self.assertEqual(c.level, ce.WARN)
        self.assertIn("docker compose", c.detail)


class TestSummary(unittest.TestCase):
    def test_counts_and_exit_rule(self):
        checks = [ce.Check("a", ce.OK, ""), ce.Check("b", ce.WARN, ""), ce.Check("c", ce.FAIL, "")]
        self.assertEqual(ce.summary(checks), "통과 1 · 주의 1 · 고칠 것 1")


if __name__ == "__main__":
    unittest.main()
