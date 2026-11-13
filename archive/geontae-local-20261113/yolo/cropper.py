import math
from pathlib import Path
import cv2
import numpy as np


def save_crop(image, bbox, path, padding=0):
    if padding < 0 or not np.isfinite(bbox).all():
        raise ValueError("Invalid bounding box or padding")
    h, w = image.shape[:2]
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Empty bounding box")
    left, top = max(0, math.floor(x1-padding)), max(0, math.floor(y1-padding))
    right, bottom = min(w, math.ceil(x2+padding)), min(h, math.ceil(y2+padding))
    if right <= left or bottom <= top:
        raise ValueError("Bounding box is outside image")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(path.suffix, image[top:bottom, left:right])
    if not ok:
        raise OSError(f"Cannot encode crop: {path}")
    encoded.tofile(str(path))
    return str(path)
