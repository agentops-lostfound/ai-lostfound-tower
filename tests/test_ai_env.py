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


def fake_db(version="160015", has_item=True, count=7, error=None):
    """check_db 용 가짜 연결: SHOW server_version_num · to_regclass · count(*) 만 흉내"""
    def connect(dsn):
        if error:
            raise error

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql):
                self.row = (version,) if "server_version" in sql else (has_item,) if "to_regclass" in sql else (count,)

            def fetchone(self):
                return self.row

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def cursor(self):
                return Cur()
        return Conn()
    return connect


DSN = {"DATABASE_URL": "postgresql://lostfound:secret-pw@localhost:5434/lostfound"}


class TestDb(unittest.TestCase):
    def test_team_db_ok(self):
        c = ce.check_db(DSN, connect=fake_db())
        self.assertEqual(c.level, ce.OK)
        self.assertIn("물건 7개", c.detail)
        self.assertIn("localhost:5434", c.detail)

    def test_other_postgres_version_is_flagged(self):
        """11/3 실제 사례: 수업용 PostgreSQL 18 이 같은 포트를 차지"""
        c = ce.check_db({**DSN, "TOWER_DB": "1"}, connect=fake_db(version="180001"))
        self.assertEqual(c.level, ce.FAIL)
        self.assertIn("PostgreSQL 18", c.detail)

    def test_password_rejected(self):
        c = ce.check_db(DSN, connect=fake_db(error=Exception('FATAL: password authentication failed for user "lostfound"')))
        self.assertEqual(c.level, ce.WARN)          # TOWER_DB 꺼져 있으면 주의
        self.assertIn("비밀번호 거절", c.detail)

    def test_down_and_missing_table_and_empty(self):
        self.assertIn("docker compose up -d", ce.check_db(DSN, connect=fake_db(error=Exception("connection timeout expired"))).detail)
        self.assertIn("item 표가 없음", ce.check_db(DSN, connect=fake_db(has_item=False)).detail)
        self.assertIn("비어 있음", ce.check_db({}).detail)

    def test_password_never_printed(self):
        for kw in ({}, {"error": Exception("password authentication failed")}, {"version": "180001"}):
            self.assertNotIn("secret-pw", ce.check_db(DSN, connect=fake_db(**kw)).line())


class TestSummary(unittest.TestCase):
    def test_counts_and_exit_rule(self):
        checks = [ce.Check("a", ce.OK, ""), ce.Check("b", ce.WARN, ""), ce.Check("c", ce.FAIL, "")]
        self.assertEqual(ce.summary(checks), "통과 1 · 주의 1 · 고칠 것 1")


if __name__ == "__main__":
    unittest.main()
