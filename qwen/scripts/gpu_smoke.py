"""Synthetic blank-image plumbing test; this is NOT a real wallet evaluation."""
import json
from pathlib import Path
from PIL import Image
from src.feature_extractor import extract_wallet_features

if __name__ == '__main__':
    features = extract_wallet_features(Image.new('RGB', (384, 256), 'white'))
    target = Path('data/output/synthetic-blank.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(features, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Synthetic blank-image GPU test only; real wallet accuracy remains unverified.')
