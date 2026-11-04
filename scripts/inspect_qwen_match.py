"""Inspect a real saved Qwen report, without re-running models or moving robots.

Run as: python -m scripts.inspect_qwen_match --report PATH --query '...'
"""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', required=True, type=Path)
    p.add_argument('--query', required=True, help='English distinctive features for MiniLM')
    p.add_argument('--category', default='unknown', help='Qwen-style category, e.g. phone')
    p.add_argument('--colors', nargs='*', default=[], help='English colors')
    p.add_argument('--sticker', choices=('present', 'absent', 'unknown'), default='unknown')
    p.add_argument('--offline', action='store_true')
    args = p.parse_args()

    from agents.backends import CompositeBackend
    from vision.adapter import VisionPart
    from matching.hybrid import HybridMatcher
    from matching.policy import load_config
    from matching.qwen_bridge import QwenMatchingPart

    report = json.loads(args.report.read_text(encoding='utf-8-sig'))
    vision = VisionPart(lambda: report, require_calibration=False)
    match = QwenMatchingPart(report, HybridMatcher(load_config(), offline=args.offline))
    backend = CompositeBackend(vision=vision, matcher=match)
    detected = backend.vision_topview()
    query = {'category': args.category, 'colors': args.colors,
             'sticker_status': args.sticker, 'free_text': args.query}
    contract_result = backend.match_item(query, detected)
    print(json.dumps({'vision_count': len(detected), 'matching_contract': contract_result,
                      'private_inspection': match.last_diagnostics,
                      'notice': 'Inspection only; robot, DB, and staff approval NOT invoked.'},
                     indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
