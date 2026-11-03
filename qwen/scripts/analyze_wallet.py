import argparse
import json
from pathlib import Path
from src.feature_extractor import extract_wallet_features

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        features = extract_wallet_features(args.image)
        target = args.output or Path('data/output') / (args.image.name + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(features, ensure_ascii=False, indent=2)
        target.write_text(text, encoding='utf-8')
        print(text)
        print(f'Saved: {target}')
        return 0
    except Exception as exc:
        print(f'Analysis failed: {exc}')
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
