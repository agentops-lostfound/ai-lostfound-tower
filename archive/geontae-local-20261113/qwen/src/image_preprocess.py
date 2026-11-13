import warnings
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError

def preprocess_image(source: str | Path | Image.Image, max_edge: int = 768):
    if max_edge < 32:
        raise ValueError('max_edge must be >= 32')
    try:
        if isinstance(source, Image.Image):
            original = source.size
            image = ImageOps.exif_transpose(source).convert('RGB')
        else:
            path = Path(source)
            if path.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
                raise ValueError('Only JPG/JPEG/PNG files are supported')
            with Image.open(path) as opened:
                if opened.format not in {'JPEG', 'PNG'}:
                    raise ValueError('File content must be JPEG or PNG')
                original = opened.size
                image = ImageOps.exif_transpose(opened).convert('RGB')
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f'Cannot read image: {source}') from exc
    if min(image.size) < 128:
        warnings.warn('Small image: visual features may be unreliable', stacklevel=2)
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return image, {'original_size': original, 'processed_size': image.size}
