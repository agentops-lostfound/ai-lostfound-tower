"""Line-oriented CPU detector worker; keeps upstream detector instances alive."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from time import perf_counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source_root.resolve()))
    # Only protocol JSON goes to stdout; upstream diagnostics go to stderr.
    with redirect_stdout(sys.stderr):
        from vision import vision_pipeline as pipeline
    original = pipeline.YoloDetector
    detectors = {}

    def cached_detector(*args, **kwargs):
        key = (tuple(str(a) for a in args), tuple(sorted((k, str(v)) for k, v in kwargs.items())))
        if key not in detectors:
            detectors[key] = original(*args, **kwargs)
        return detectors[key]

    pipeline.YoloDetector = cached_detector
    print(json.dumps({'ready': True}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if request.get('stop'):
                return 0
            started = perf_counter()
            with redirect_stdout(sys.stderr):
                report, path = pipeline.run_image(request['image'], request.get('config'), 'cpu')
            response = {'ok': True, 'path': str(path), 'worker_seconds': perf_counter()-started}
        except Exception as exc:
            response = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        print(json.dumps(response), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
