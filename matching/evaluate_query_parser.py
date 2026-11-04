"""Small manually labeled extraction smoke test; not a general accuracy benchmark."""
import argparse
import json
from pathlib import Path
from .query_parser import QueryParser


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--offline", action="store_true")
    cli.add_argument("--output", type=Path, default=Path("outputs/matching/query_parser/results.json"))
    args = cli.parse_args()
    cases = json.loads((Path(__file__).parent / "configs/query_parser_cases.json").read_text(encoding="utf-8"))
    model = QueryParser(offline=args.offline)
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        try:
            result = model.parse(case["text"])
            values = {**result["features"], "needs_clarification": result["needs_clarification"]}
            failures = [key for key, value in case["expected"].items()
                        if (set(values[key]) != set(value) if key == "colors" else values[key] != value)]
            results.append({**case, "result": result, "mismatched_fields": failures})
        except (ValueError, RuntimeError) as error:
            results.append({**case, "error": str(error), "raw_output": getattr(error, "raw_output", None),
                            "mismatched_fields": ["parse_error"]})
        report = {"model": model.model_id, "init_seconds": model.init_seconds,
                  "passed": sum(not r["mismatched_fields"] for r in results),
                  "completed": len(results), "cases": results}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"completed": len(results), "passed": report["passed"],
                          "mismatched_fields": results[-1]["mismatched_fields"]}), flush=True)
    return 0 if report["passed"] == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
