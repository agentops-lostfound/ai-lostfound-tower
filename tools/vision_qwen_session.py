"""Experimental CPU YOLO -> resident GPU Qwen session. No robot control."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter


def detect(root, python, image, config):
    code = (
        'import sys; from vision.vision_pipeline import run_image; '
        'r,p=run_image(sys.argv[1],sys.argv[2] or None,"cpu"); '
        'print("VISION_REPORT="+str(p))'
    )
    completed = subprocess.run([str(python), '-c', code, str(image), str(config or '')],
                               cwd=root, text=True, encoding='utf-8', errors='replace',
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout or 'Detection failed')
    lines = [line for line in completed.stdout.splitlines() if line.startswith('VISION_REPORT=')]
    if not lines:
        raise RuntimeError('Detector did not return a report path')
    path = Path(lines[-1].split('=', 1)[1])
    return json.loads(path.read_text(encoding='utf-8')), path


def save(path, report):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--vision-python', required=True, type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--max-edge', type=int, default=384)
    args = parser.parse_args()
    root, python = args.source_root.resolve(), args.vision_python.resolve()
    config = args.config.resolve() if args.config else None
    required = [root / 'vision/vision_pipeline.py', root / 'vision/item_features.py',
                root / 'qwen/config/settings.py', root / 'qwen/src/model_loader.py', python]
    if args.max_edge < 32 or any(not p.is_file() for p in required) or (config and not config.is_file()):
        parser.error('Check source, Python, config paths and max-edge >= 32')
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'qwen'))
    from config.settings import Settings
    from src.model_loader import load_model
    from vision.item_features import extract_item_features
    settings = replace(Settings(), max_edge=args.max_edge, offline=True,
                       log_dir=root / 'outputs/resident-sequence/logs')
    started = perf_counter()
    load_model(settings)
    print(f'READY: startup {perf_counter()-started:.2f}s; CPU YOLO, resident Qwen, '
          f'max_edge={args.max_edge}. Enter photo path or exit.', flush=True)
    while True:
        try:
            text = input('Photo> ').strip().strip('\"\'')
        except (EOFError, KeyboardInterrupt):
            return 0
        if text.lower() in ('exit', 'quit'):
            return 0
        if not text:
            continue
        image = Path(text)
        if not image.is_absolute():
            image = root / image
        if not image.is_file():
            print('File not found; enter the full photo path.', flush=True)
            continue
        started = perf_counter()
        target, report = None, None
        try:
            report, source = detect(root, python, image, config)
            detection_seconds = perf_counter() - started
            target = source.parent / 'resident_result.json'
            report['resident_sequence'] = {'status': 'running', 'visual_accuracy_verified': False,
                'detection_seconds': detection_seconds, 'max_edge': args.max_edge}
            for obj in report['objects']:
                obj['qwen'] = {'status': 'pending', 'features': None}
            save(target, report)
            for obj in report['objects']:
                crop_started = perf_counter()
                features = extract_item_features(obj['crop_path'], settings)
                obj['qwen'] = {'status': 'ok', 'features': features,
                               'elapsed_seconds': perf_counter() - crop_started}
                save(target, report)
            report['resident_sequence'].update(
                status='complete' if report['objects'] else 'no_detections',
                total_seconds=perf_counter() - started)
            save(target, report)
            print(json.dumps({'result': str(target), 'debug': report.get('debug_path'),
                'objects': len(report['objects']), 'sequence': report['resident_sequence']},
                ensure_ascii=False, indent=2), flush=True)
        except (Exception, KeyboardInterrupt) as exc:
            if target and report:
                for obj in report['objects']:
                    if obj['qwen']['status'] == 'pending':
                        obj['qwen']['status'] = 'cancelled' if isinstance(exc, KeyboardInterrupt) else 'failed'
                report['resident_sequence'].update(status='cancelled' if isinstance(exc, KeyboardInterrupt)
                    else 'failed', error=type(exc).__name__, total_seconds=perf_counter()-started)
                save(target, report)
            print(f'Session stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 130 if isinstance(exc, KeyboardInterrupt) else 1


if __name__ == '__main__':
    raise SystemExit(main())
