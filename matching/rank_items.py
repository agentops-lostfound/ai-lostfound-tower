"""English query -> cached CPU MiniLM -> Qwen candidate ranking."""
import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4
from .embedding import ROOT, MODEL, read_candidates
from .policy import DEFAULT_CONFIG, load_config, attributes
from .hybrid import HybridMatcher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="English description; translation is a separate step")
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--query-features", type=Path, help="Explicit structured conditions JSON; no automatic extraction")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--benchmark", type=int, default=0, help="Extra warm requests on the same loaded model")
    args = parser.parse_args()
    if args.threads < 1 or not 0 <= args.benchmark <= 100:
        parser.error("threads >= 1 and benchmark in 0..100 required")
    started = perf_counter()
    try:
        config = load_config(args.config)
        constraints = json.loads(args.query_features.read_text(encoding="utf-8-sig")) if args.query_features else {"free_text": args.query}
        attributes(constraints)
        if set(constraints) - {"category", "colors", "sticker_status", "free_text"}:
            raise ValueError("Query features support category, colors, sticker_status, free_text")
        data = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
        candidates, skipped = read_candidates(data)
        matcher = HybridMatcher(config, threads=args.threads, offline=args.offline)
        ranking, decision, timing = matcher.match(candidates, constraints)
        warm = []
        for _ in range(args.benchmark):
            begin = perf_counter()
            matcher.match(candidates, constraints)
            warm.append(perf_counter()-begin)
        ranker = matcher.ranker
        prep = {"total_candidate_count": len(candidates)}
        report = {"status": decision["status"], "decision": decision, "config": config,
                  "query_features": constraints, "model": MODEL,
                  "provider": "CPUExecutionProvider", "query": args.query,
                  "source": str(args.candidates.resolve()), "ranking": ranking, "skipped": skipped,
                  "notice": "Experimental policy; scores are not probabilities. Structured conditions are supplied separately, not extracted from query. No robot action is performed.",
                  "timing": {"model_init_seconds": ranker.init_seconds if ranker else 0,
                             **prep, **timing, "warm_samples": len(warm),
                             "warm_median_seconds": median(warm) if warm else None,
                             "warm_seconds": warm, "total_seconds": perf_counter()-started}}
        output = args.output or ROOT / "outputs/matching" / uuid4().hex / "ranking.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Matching failed: {error}\n")
    print(json.dumps({"result": str(output.resolve()), "decision": decision, "ranking": [
        {"id": item["id"], "cosine_similarity": round(item["cosine_similarity"],4) if item["cosine_similarity"] is not None else None,
         "final_score": round(item["final_score"],4), "eligible": item["eligible"],
         "rejection_reasons": item["rejection_reasons"]} for item in ranking],
        "timing": report["timing"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
