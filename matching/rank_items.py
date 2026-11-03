"""English query -> cached CPU MiniLM -> Qwen candidate ranking."""
import argparse
import json
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4
from .embedding import ROOT, MODEL, MiniLMRanker, read_candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="English description; translation is a separate step")
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--benchmark", type=int, default=0, help="Extra warm requests on the same loaded model")
    args = parser.parse_args()
    if args.threads < 1 or not 0 <= args.benchmark <= 100:
        parser.error("threads >= 1 and benchmark in 0..100 required")
    started = perf_counter()
    try:
        data = json.loads(args.candidates.read_text(encoding="utf-8-sig"))
        candidates, skipped = read_candidates(data)
        ranker = MiniLMRanker(threads=args.threads, offline=args.offline) if candidates else None
        prep = ranker.prepare(candidates) if ranker else {"candidate_count": 0}
        ranking, timing = ranker.rank(args.query) if ranker else ([], {})
        warm = []
        for _ in range(args.benchmark if ranker else 0):
            begin = perf_counter()
            ranker.rank(args.query)
            warm.append(perf_counter()-begin)
        report = {"status": "ranked" if ranking else "no_candidates", "model": MODEL,
                  "provider": "CPUExecutionProvider", "query": args.query,
                  "source": str(args.candidates.resolve()), "ranking": ranking, "skipped": skipped,
                  "notice": "Cosine similarity is not a probability. No automatic item selection; color/text contradictions and unknown observations need separate evaluation.",
                  "timing": {"model_init_seconds": ranker.init_seconds if ranker else 0,
                             **prep, **timing, "warm_samples": len(warm),
                             "warm_median_seconds": median(warm) if warm else None,
                             "warm_seconds": warm, "total_seconds": perf_counter()-started}}
        output = args.output or ROOT / "outputs/matching" / uuid4().hex / "ranking.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    except (ImportError, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Matching failed: {error}\n")
    print(json.dumps({"result": str(output.resolve()), "ranking": [
        {"id": item["id"], "cosine_similarity": round(item["cosine_similarity"],4)} for item in ranking],
        "timing": report["timing"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
