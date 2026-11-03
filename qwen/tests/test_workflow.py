"""Failure handling tests use fake inference, never claim GPU execution."""
import json
import sys
from scripts import analyze_batch

def test_batch_continues_and_keeps_extensions(tmp_path, monkeypatch):
    incoming = tmp_path/'input'
    incoming.mkdir()
    for name in ['a.jpg', 'a.png', 'bad.jpg']:
        (incoming/name).touch()
    calls = []
    def fake(image):
        calls.append(image.name)
        if image.name == 'bad.jpg':
            raise ValueError('corrupt image')
        return {'source': image.name}
    monkeypatch.setattr(analyze_batch, 'extract_wallet_features', fake)
    out = tmp_path/'out'
    monkeypatch.setattr(sys, 'argv', ['batch', '--input', str(incoming), '--output', str(out)])
    assert analyze_batch.main() == 1
    assert calls == ['a.jpg','a.png','bad.jpg']
    assert json.loads((out/'a.jpg.json').read_text())['source'] == 'a.jpg'
    assert (out/'a.png.json').exists()
    assert not (out/'bad.jpg.json').exists()
