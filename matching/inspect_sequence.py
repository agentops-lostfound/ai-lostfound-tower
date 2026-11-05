"""Offline LF-3 -> LF-20 inspection; no model inference for images or robot calls."""
import argparse
import csv
import json
from pathlib import Path

from agents.vision_adapter import adapt_report
from .hybrid import HybridMatcher
from .korean_query import KoreanFirstParser
from .policy import load_config
from .qwen_bridge import QwenMatchingPart
from .query_parser import guard_query_constraints, guard_decision


def inspect(report, parsed, matcher):
    detections = adapt_report(report)
    bridge = QwenMatchingPart(report, matcher)
    contract = bridge.match_item(parsed['features'], detections)
    diagnostics = bridge.last_diagnostics or {}
    ranking = diagnostics.get('ranking', [])
    decision = diagnostics.get('engine_decision')
    return {'objects': len(report.get('objects', [])), 'adapter_objects': len(detections),
            'contract_result': contract, 'engine_decision': diagnostics.get('engine_decision'),
            'query_policy_decision': guard_query_constraints(decision, parsed) if decision else None,
            'final_decision': guard_decision(decision, parsed) if decision else None,
            'ranking': ranking, 'top3': [r for r in ranking if r['eligible']][:3],
            'robot_authorized': False, 'human_ground_truth': None,
            'review_required': bool(parsed.get('requires_review', True))}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument('--report', type=Path)
    source.add_argument('--batch', type=Path, action='append', help='Repeat for 512/384 summaries')
    cli.add_argument('--queries', type=Path, default=Path(__file__).parent/'configs/lf20_inspection_queries.json')
    cli.add_argument('--output-dir', type=Path, required=True)
    args = cli.parse_args()
    queries = json.loads(args.queries.read_text(encoding='utf-8-sig'))
    parser = KoreanFirstParser(offline=True)
    parsed = [(q, parser.parse(q['text'])) for q in queries]
    matcher = HybridMatcher(load_config(), offline=True)
    scenes = []
    if args.report:
        scenes.append(('single', args.report.stem, args.report))
    else:
        for batch in args.batch:
            with (batch/'summary.csv').open(encoding='utf-8-sig', newline='') as f:
                scenes.extend((batch.name, r['image'], Path(r['result_json'])) for r in csv.DictReader(f))
    results = []
    for batch, image, path in scenes:
        report = json.loads(path.read_text(encoding='utf-8-sig'))
        for query, extraction in parsed:
            result = inspect(report, extraction, matcher)
            results.append({'batch': batch, 'image': image, 'report': str(path),
                            'query_id': query['id'], 'query': query['text'],
                            'parsed': extraction, **result})
        print(f'{batch}/{image}: {len(report.get("objects", []))} objects', flush=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/'results.json').write_text(json.dumps({
        'notice': 'Inspection only. Scenes are separate; no cross-photo registration or deduplication. Human labels pending; scores are not probabilities.',
        'results': results}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    with (args.output_dir/'summary.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['batch','image','query_id','engine_status','top_id','query_policy_status','query_policy_reasons','contract_status','bridge_reason','top3','ground_truth'])
        for r in results:
            decision = r['engine_decision'] or {}
            writer.writerow([r['batch'],r['image'],r['query_id'],decision.get('status'),
                             decision.get('top_candidate_id'),(r['query_policy_decision'] or {}).get('status'),
                             json.dumps((r['query_policy_decision'] or {}).get('reasons', [])),r['contract_result']['status'],
                             r['contract_result']['reason'],json.dumps(r['top3']), 'unreviewed'])
    print(f'Saved {len(results)} comparisons to {args.output_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
