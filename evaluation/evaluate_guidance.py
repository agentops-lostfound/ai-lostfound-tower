"""Repeatable, authored guidance question regression set; not independent accuracy."""
import json
from pathlib import Path
from agents.guidance import Guidance


def evaluate():
    guide = Guidance()
    cases = json.loads((Path(__file__).parent / "guidance_questions.json").read_text(encoding="utf-8"))
    results = []
    for case in cases:
        try:
            response = guide.ask(case["question"])
        except ValueError:
            response = {"status": "rejected", "sources": [], "answer": ""}
        topics = {s.get("topic") for s in response["sources"]}
        passed = response["status"] == case["expected_status"] and set(case["expected_topics"]) <= topics
        if case["group"] in ("기간", "지시문") and "30일" in response["answer"]:
            passed = False
        results.append({**case, "passed": passed, "response": response})
    return {"total": len(results), "passed": sum(r["passed"] for r in results), "cases": results}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{result['passed']}/{result['total']}")
    for r in result["cases"]:
        if not r["passed"]:
            print(r["question"], r["response"]["status"], "expected", r["expected_status"])
