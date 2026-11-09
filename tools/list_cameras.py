"""관제탑 PC 에 꽂힌 카메라 번호 찾기 (LF-2 · 11/9 변재원) — .env TOWER_KIOSK_CAMERAS 에 넣을 번호 확인용

한줄 설명: OpenCV 카메라 번호 0~7 을 하나씩 열어 보고, 열리는 번호의 해상도와 사진 한 장을 저장한다.
사진(data/camera_check/cam_N.jpg)을 열어 보면 몇 번이 상자 위 웹캠이고 몇 번이 탑뷰·노트북 카메라인지 알 수 있다.

사용법 (저장소 폴더, .venv 켠 상태, 관제탑이 카메라를 쓰고 있지 않을 때)
    python tools/list_cameras.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(limit: int = 8) -> int:
    import cv2
    from agents.kiosk_camera import _open
    out = ROOT / "data" / "camera_check"
    out.mkdir(parents=True, exist_ok=True)
    found = 0
    for i in range(limit):
        cap = _open(i)
        try:
            if not cap.isOpened():
                print(f"[{i}] 없음")
                continue
            ok, frame = False, None
            for _ in range(10):                      # 웹캠은 처음 몇 장이 검게 나올 수 있음
                ok, frame = cap.read()
            if not ok or frame is None:
                print(f"[{i}] 열리지만 영상 없음(다른 프로그램이 사용 중일 수 있음)")
                continue
            h, w = frame.shape[:2]
            path = out / f"cam_{i}.jpg"
            cv2.imwrite(str(path), frame)
            found += 1
            print(f"[{i}] 열림 {w}x{h} → 사진 {path.relative_to(ROOT)}")
        finally:
            cap.release()
    print(f"\n열린 카메라 {found}개. 상자 위 웹캠 번호를 .env 에 적으세요. 예) TOWER_KIOSK_CAMERAS=KIOSK-A=1")
    if os.name == "nt":
        print("사진 폴더 열기: explorer data\\camera_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
