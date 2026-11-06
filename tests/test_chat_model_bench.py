"""tools/chat_model_bench.py — Ollama 없이 가짜 모델로 비교표 확인 (LF-5, 11/5)"""
import json
import tempfile
import unittest
from pathlib import Path

from tools import chat_model_bench as bench


def good_model(payload):
    """받은 문단을 모두 고르는 가짜 모델(형식은 Ollama /api/chat 응답과 같음)"""
    passages = json.loads(payload["messages"][1]["content"])["retrieved_passages"]
    return {"message": {"content": json.dumps({"passage_ids": [p["id"] for p in passages]})}}


def dead_model(payload):
    raise ConnectionRefusedError("Ollama 꺼짐")


class Clock:
    def __init__(self, step=0.01):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


class BenchTests(unittest.TestCase):
    def setUp(self):
        self.cases = bench.load_cases()

    def test_baseline_matches_existing_evaluation(self):
        from evaluation.evaluate_guidance import evaluate
        r = bench.run_model(bench.BASELINE, self.cases)
        self.assertEqual((r["total"], r["passed"]), (evaluate()["total"], evaluate()["passed"]))
        self.assertEqual((r["model_called"], r["generated"], r["fallback"]), (0, 0, 0))

    def test_good_model_is_used_and_keeps_status(self):
        base = bench.run_model(bench.BASELINE, self.cases)
        r = bench.run_model("fake-good", self.cases, request=good_model, clock=Clock())
        self.assertGreater(r["model_called"], 0)
        self.assertGreater(r["generated"], 0)
        self.assertEqual(r["model_called"], r["generated"] + r["fallback"])
        self.assertEqual(r["passed"], base["passed"])                   # 모델은 문단만 고르므로 상태가 바뀌지 않아야 함
        self.assertEqual(r["p50_ms"], 10.0)                              # 가짜 시계: 질문마다 10ms

    def test_dead_model_falls_back_and_is_explained(self):
        r = bench.run_model("fake-dead", self.cases, request=dead_model)
        self.assertEqual(r["generated"], 0)
        self.assertEqual(r["fallback"], r["model_called"])
        text = bench.report([bench.run_model(bench.BASELINE, self.cases), r])
        self.assertIn("ollama list", text)
        self.assertIn("| 없음(문서 원문) |", text)

    def test_cli_limit_and_files(self):
        with tempfile.TemporaryDirectory() as d:
            out, js = Path(d) / "r" / "bench.md", Path(d) / "bench.json"
            text = bench.main(["--models", "fake-good,none", "--limit", "5", "--out", str(out), "--json", str(js)],
                              request=good_model)
            rows = json.loads(js.read_text(encoding="utf-8"))
            self.assertEqual([r["model"] for r in rows], ["none", "fake-good"])   # none 은 한 번만, 맨 앞
            self.assertEqual(rows[0]["total"], 5)
            self.assertEqual(out.read_text(encoding="utf-8"), text)
            self.assertIn("질문 5개", text)


if __name__ == "__main__":
    unittest.main()


class RatingSheetTests(unittest.TestCase):
    """11/6 사람 품질 평가표: 모델 이름을 가리고 모델이 답한 질문만"""

    def test_rating_csv_is_blind_and_has_key(self):
        import csv
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rating.csv"
            text = bench.main(["--models", "fake-good,fake-dead", "--limit", "40", "--rating", str(path)], request=good_model)
            self.assertIn("사람 평가표", text)
            with path.open(encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
            header, body = rows[0], rows[1:]
            self.assertEqual(header[:2], ["번호", "질문"])
            self.assertIn("답 A", header)
            self.assertNotIn("fake-good", path.read_text(encoding="utf-8-sig"))    # 모델 이름이 표에 없음
            self.assertTrue(0 < len(body) <= 20)
            key = json.loads(path.with_suffix(".key.json").read_text(encoding="utf-8"))
            self.assertEqual(set(key["letters"].values()), {"fake-good", "fake-dead"})
            self.assertEqual(key["questions"], len(body))
