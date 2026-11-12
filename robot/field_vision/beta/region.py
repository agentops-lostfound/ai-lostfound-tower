"""탑뷰 보관함 영역: 정규화된 직사각형, 전체 영상 좌표 유지."""
import cv2
import numpy as np

# 현재 HD 탑뷰에서 보관함과 두 마커를 포함하는 초기 영역.
DEFAULT_REGION = [0.084375, 0.130556, 0.932031, 0.854167]


def find_region(image):
    hsv = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2HSV)
    mask = cv2.inRange(hsv, np.array([30, 35, 35]), np.array([100, 255, 255]))
    kernel = np.ones((15, 15), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) > image.width * image.height * .15]
    if not contours:
        raise ValueError('초록색 보관함 영역을 찾지 못했습니다. 수동으로 지정하세요.')
    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    return [max(0, (x-8)/image.width), max(0, (y-8)/image.height),
            min(1, (x+w+8)/image.width), min(1, (y+h+8)/image.height)]


def pixel_box(image, region):
    return tuple(round(v * (image.width if i % 2 == 0 else image.height)) for i, v in enumerate(region))
