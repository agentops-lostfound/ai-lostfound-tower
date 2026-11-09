"""Named pixel crops for a fixed camera and worktable."""

import json


def validate_pixel_bounds(bounds, image_size):
    if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
            or any(type(value) is not int for value in bounds)):
        raise ValueError('Pixel bounds must contain four integers')
    left, top, right, bottom = bounds
    width, height = image_size
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError('Pixel bounds must have positive area and fit inside the photo')


def crop_pixels(image, bounds):
    validate_pixel_bounds(bounds, image.shape[1::-1])
    left, top, right, bottom = bounds
    return image[top:bottom, left:right]


def contains_bounds(outer, inner):
    left, top, right, bottom = outer
    x1, y1, x2, y2 = inner
    return left <= x1 and top <= y1 and x2 <= right and y2 <= bottom


def load_regions(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('regions'), dict):
        raise ValueError('Region file must contain an image size and named regions')
    size = data.get('image_size_px')
    if not isinstance(size, list) or len(size) != 2 or any(type(n) is not int or n < 1 for n in size):
        raise ValueError('image_size_px must contain the reference width and height')
    cabinet = data.get('cabinet_bounds_px')
    if cabinet is not None:
        validate_pixel_bounds(cabinet, size)
    for name, bounds in data['regions'].items():
        validate_pixel_bounds(bounds, size)
        if cabinet is not None and not contains_bounds(cabinet, bounds):
            raise ValueError(f'Region {name} is outside the cabinet boundary')
    return data
