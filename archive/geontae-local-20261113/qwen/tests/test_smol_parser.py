import pytest
from scripts.diagnose_smolvlm import parse_features

def response(color='black',shape='rectangular',logo='unknown',sticker='unknown',position='unknown'):
    return f'Color: {color}\nShape: {shape}\nVisible logo or text: {logo}\nSticker shape: {sticker}\nSticker position: {position}'

def test_observed_only():
    value = parse_features(response(color='black and brown',logo='Aldebran'))
    assert value['category']=='unknown' and value['wallet_type'] is None and value['materials']==[]
    assert value['colors']==['black','brown'] and value['logos_or_text']==['Aldebran']
    assert value['sticker_status']=='unknown' and value['stickers']==[]

def test_explicit_absence_and_present():
    assert parse_features(response(sticker='none',position='none'))['sticker_status']=='absent'
    value=parse_features(response(sticker='circle'))
    assert value['stickers']==[{'shape':'circle','position':None}]

@pytest.mark.parametrize('raw',[
    'a black wallet',response()+'\nExtra: invented',response()+'\nColor: red',
    response(color='maybe black'), response(sticker='none',position='bottom'),
    response(color='unknown',shape='unknown'), response().replace('Shape: rectangular\n','')])
def test_reject_unsupported_or_empty(raw):
    with pytest.raises(ValueError):
        parse_features(raw)
