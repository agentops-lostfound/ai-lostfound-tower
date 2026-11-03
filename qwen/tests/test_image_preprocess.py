import pytest
from PIL import Image
from src.image_preprocess import preprocess_image

@pytest.mark.parametrize('extension', ['jpg','png'])
def test_files(tmp_path, extension):
    path = tmp_path / ('image.'+extension)
    Image.new('RGB', (1000,500)).save(path)
    image, sizes = preprocess_image(path, 500)
    assert image.size == (500,250)
    assert sizes['original_size'] == (1000,500)

def test_pil():
    source = Image.new('RGBA', (200,150))
    result, _ = preprocess_image(source)
    assert result.mode == 'RGB' and result.size == source.size

def test_corrupt(tmp_path):
    path = tmp_path/'bad.png'
    path.write_text('not an image')
    with pytest.raises(ValueError):
        preprocess_image(path)

def test_missing(tmp_path):
    with pytest.raises(ValueError):
        preprocess_image(tmp_path/'missing.jpg')

def test_exif(tmp_path):
    path = tmp_path/'rotated.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB',(300,150)).save(path, exif=exif)
    result, info = preprocess_image(path)
    assert result.size == (150,300) and info['original_size'] == (300,150)
