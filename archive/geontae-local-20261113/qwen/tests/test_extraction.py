import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from PIL import Image
from config.settings import Settings
from src import feature_extractor as extractor

def fake_runtime(monkeypatch, responses):
    import torch
    for name in ['synchronize', 'reset_peak_memory_stats']:
        monkeypatch.setattr(torch.cuda, name, lambda: None)
    for name in ['max_memory_allocated', 'max_memory_reserved']:
        monkeypatch.setattr(torch.cuda, name, lambda: 0)
    class Inputs(dict):
        def to(self, device):
            return self
    processor = SimpleNamespace(
        apply_chat_template=lambda *a, **kw: Inputs(input_ids=torch.zeros((1,2),dtype=torch.long)),
        batch_decode=Mock(side_effect=[[text] for text in responses]))
    model = SimpleNamespace(generate=Mock(return_value=torch.zeros((1,4),dtype=torch.long)))
    bundle = SimpleNamespace(model=model, processor=processor, metadata={})
    monkeypatch.setattr(extractor, 'load_model', lambda settings: bundle)
    return bundle

def test_retry_exhausted_logs_raw(tmp_path, monkeypatch):
    bundle = fake_runtime(monkeypatch, ['bad one','bad two'])
    with pytest.raises(extractor.ExtractionError):
        extractor.extract_wallet_features(Image.new('RGB',(200,200)), Settings(log_dir=tmp_path))
    assert bundle.model.generate.call_count == 2
    assert len(list(tmp_path.glob('invalid-*.json'))) == 2
    record = json.loads(next(tmp_path.glob('benchmark-*.json')).read_text())
    assert record['validation_success'] is False

def test_retry_then_success(tmp_path, monkeypatch):
    valid = dict(category='unknown', colors=[], shape=None, wallet_type=None, materials=[],
                 logos_or_text=[], sticker_status='unknown', stickers=[], distinctive_features=[])
    bundle = fake_runtime(monkeypatch, ['bad',json.dumps(valid)])
    assert extractor.extract_wallet_features(Image.new('RGB',(200,200)), Settings(log_dir=tmp_path)) == valid
    assert bundle.model.generate.call_args.kwargs['do_sample'] is False
