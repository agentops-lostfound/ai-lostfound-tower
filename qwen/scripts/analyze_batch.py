import argparse
import json
from pathlib import Path
from time import perf_counter
from src.feature_extractor import extract_wallet_features

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', default=Path('data/output'), type=Path)
    args = parser.parse_args()
    if not args.input.is_dir():
        parser.error('Input directory does not exist')
    files = sorted(p for p in args.input.iterdir() if p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png'})
    if not files:
        print('No images found')
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    failed = 0
    for image in files:
        start = perf_counter()
        try:
            features = extract_wallet_features(image)
            # Keep extension in filename to avoid a.jpg/a.png collisions.
            (args.output / (image.name + '.json')).write_text(
                json.dumps(features, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            failed += 1
            print(f'Failed {image.name}: {exc}')
        print(f'{image.name}: {perf_counter()-start:.3f}s')
    print(f'Success: {len(files)-failed}; Failed: {failed}')
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
