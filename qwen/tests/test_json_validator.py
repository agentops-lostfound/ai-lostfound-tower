import json
import pytest
from src.json_validator import validate_response

def test_json():
    value = dict(category='unknown', colors=[], shape=None, wallet_type=None, materials=[],
                 logos_or_text=[], sticker_status='unknown', stickers=[], distinctive_features=[])
    assert validate_response('```json\n'+json.dumps(value)+'\n```').category == 'unknown'

@pytest.mark.parametrize('raw', ['not json', '{}', '{"category":"wallet","category":"other"}',
                              '{"colors":NaN}', 'prefix {} suffix'])
def test_invalid(raw):
    with pytest.raises(ValueError):
        validate_response(raw)
