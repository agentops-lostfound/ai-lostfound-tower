import pytest
from pydantic import ValidationError
from src.schemas import WalletFeatures

@pytest.fixture
def payload():
    return dict(category='wallet', colors=['black','brown'], shape=None, wallet_type=None,
                materials=[], logos_or_text=[], sticker_status='unknown', stickers=[], distinctive_features=[])

def test_valid(payload):
    assert WalletFeatures.model_validate(payload).shape is None

@pytest.mark.parametrize('change', [dict(colors='black'), dict(category='bag'),
    dict(unexpected=True), dict(sticker_status='present'), dict(colors=[1])])
def test_invalid(payload, change):
    with pytest.raises(ValidationError):
        WalletFeatures.model_validate({**payload, **change})

def test_required(payload):
    del payload['shape']
    with pytest.raises(ValidationError):
        WalletFeatures.model_validate(payload)
