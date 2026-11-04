"""Keep the existing Qwen model alive for sequential local photo requests.

No server, source modification, robot calls or inference-result cache.
"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--profile', action='store_true', help='Time extraction stages with CUDA synchronization')
    parser.add_argument('--concise', action='store_true', help='Experimental concise values; preserves all eight keys')
    parser.add_argument('--max-edge', type=int, default=512,
                        help='Maximum image edge; baseline 512, experimental 384')
    args = parser.parse_args()
    if args.max_edge < 32:
        parser.error('--max-edge must be at least 32')
    root = args.source_root.resolve()
    for relative in ('qwen/config/settings.py', 'qwen/src/model_loader.py',
                     'vision/item_features.py'):
        if not (root / relative).is_file():
            parser.error(f'Missing source: {root / relative}')
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'qwen'))
    from dataclasses import replace
    from config.settings import Settings
    from src.model_loader import load_model
    from vision.item_features import extract_item_features
    if args.concise:
        import vision.item_features as feature_module
        # Process-local experiment only; no upstream files or schema changed.
        feature_module.PROMPT += (
            '\nFor this experiment, keep all eight keys and the same observations, '
            'but express values as short phrases, not sentences. '
            'Keep exact legible text, distinguishing colors and sticker location. '
            'Avoid repeating facts across fields; distinctive_features may be empty '
            'when it adds no new identifying information. '
            'Do not drop observed identifying details merely to be shorter. '
            'Return compact JSON without explanatory prose. Template follows:\n')
    # Exactly the same immutable Settings instance for preload and every request:
    # the upstream lru_cache key includes log_dir and all other settings.
    settings = replace(Settings(), max_edge=args.max_edge, offline=True,
                       log_dir=root / 'outputs/qwen-session/logs')
    started = perf_counter()
    bundle = load_model(settings)
    print(f'READY: startup {perf_counter() - started:.2f}s. '
          'Enter a JPG/PNG path; type exit to release the process. '
          'First inference is not a warmed benchmark.', flush=True)
    request_no = 0
    while True:
        try:
            text = input('Photo> ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ('exit', 'quit'):
            break
        if not text:
            continue
        # PowerShell path-copy commonly includes surrounding quotes.
        photo = Path(text.strip('\"\'')).expanduser()
        if not photo.is_absolute():
            photo = root / photo
        if not photo.is_file():
            print('File not found; enter the full image path.', flush=True)
            continue
        request_no += 1
        started = perf_counter()
        try:
            profile = None
            if args.profile:
                import torch
                import vision.item_features as feature_module
                from qwen_profile import profile_request
                with profile_request(bundle, feature_module, torch) as profile:
                    features = extract_item_features(photo, settings)
            else:
                features = extract_item_features(photo, settings)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            # Stop after inference errors; do not automatically rerun a damaged
            # CUDA session or silently change execution settings.
            print(f'Inference failed ({type(exc).__name__}): {exc}', file=sys.stderr)
            return 1
        elapsed = perf_counter() - started
        result = {'request': request_no, 'request_seconds': round(elapsed, 4),
                  'mode': 'concise' if args.concise else 'baseline',
                  'max_edge': args.max_edge, 'features': features}
        if profile is not None:
            measured = sum(profile.get(k, 0.0) for k in (
                'processor_seconds', 'generate_seconds', 'decode_seconds', 'validation_seconds'))
            profile['other_seconds'] = max(0.0, elapsed - measured)
            profile['other_includes'] = 'preprocessing, GPU transfer, logging, instrumentation overhead'
            result['profile'] = profile
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
