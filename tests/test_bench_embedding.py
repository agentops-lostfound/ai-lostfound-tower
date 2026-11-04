"""tools/bench_embedding.py 시험 — 진짜 모델 없이 가짜 모델로 계산 흐름만 확인."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import bench_embedding as be  # noqa: E402


class FakeModel:
    """같은 물건 쌍은 비슷한 벡터, 다른 쌍은 다른 벡터가 나오게: 문장에 들어간 물건 단어로 축을 고른다"""
    AXES = [("지갑", "wallet"), ("휴대폰", "phone"), ("립밤", "lip balm"), ("주황", "red"), ("갈색", "brown"),
            ("별", "star"), ("긁", "scratch"), ("검은", "black"), ("하얀", "white")]

    def encode(self, texts):
        out = []
        for t in texts:
            v = [1.0 if (ko in t or en in t) else 0.0 for ko, en in self.AXES]
            out.append([x + 0.01 for x in v])
        return out


class BenchTest(unittest.TestCase):
    def test_bench_runs_and_separates(self):
        r = be.bench("fake-model", lambda m: FakeModel(), n=5)
        self.assertAlmostEqual(r["gap"], r["same_min"] - r["diff_max"])
        self.assertGreater(r["gap"], 0)          # 같은 물건(색·표시까지 겹침) > 다른 물건(품목만 겹침)
        self.assertGreaterEqual(r["ms_p95"], 0)
        self.assertEqual(r["model"], "fake-model")

    def test_e5_prefix(self):
        self.assertEqual(be.prefixed("intfloat/multilingual-e5-small", "a", "q"), "query: a")
        self.assertEqual(be.prefixed("intfloat/multilingual-e5-small", "a", "p"), "passage: a")
        self.assertEqual(be.prefixed("BAAI/bge-m3", "a", "q"), "a")

    def test_pairs_balanced(self):
        self.assertEqual(sum(p[2] for p in be.PAIRS), sum(not p[2] for p in be.PAIRS))
        self.assertAlmostEqual(be.cosine([1, 0], [1, 0]), 1.0)
        self.assertEqual(be.cosine([0, 0], [1, 0]), 0.0)

    def test_missing_package_message(self):
        import builtins
        real = builtins.__import__

        def fake(name, *a, **k):
            if name == "sentence_transformers":
                raise ImportError
            return real(name, *a, **k)
        builtins.__import__ = fake
        try:
            self.assertEqual(be.main(["--n", "1"]), 1)
        finally:
            builtins.__import__ = real


if __name__ == "__main__":
    unittest.main()
