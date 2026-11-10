"""관제탑 PC 에 꽂힌 카메라 번호 찾기 (LF-2 · 11/9 변재원) — .env TOWER_KIOSK_CAMERAS 에 넣을 번호 확인용

한줄 설명: OpenCV 카메라 번호 0~7 을 하나씩 열어 보고, 열리는 번호의 해상도·밝기와 사진 한 장을 저장한다.
사진(data/camera_check/cam_N.jpg)을 열어 보면 몇 번이 상자 위 웹캠이고 몇 번이 탑뷰·노트북 카메라인지 알 수 있다.

사용법 (저장소 폴더, .venv 켠 상태)
    python tools/list_cameras.py
주의: 관제탑이 그 웹캠을 쓰는 중이면(키오스크 화면이 서버 카메라를 보고 있으면) "없음"·"검은 화면"으로 나올 수 있다.
      키오스크 탭을 닫고 1분 기다리거나 관제탑을 끈 뒤 돌린다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(limit: int = 8) -> int:
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)    # 없는 번호마다 나오는 경고 줄 숨김
    except Exception:
        pass
    from agents.kiosk_camera import _open, is_dark
    out = ROOT / "data" / "camera_check"
    out.mkdir(parents=True, exist_ok=True)
    found, bright = 0, []
    for i in range(limit):
        cap = _open(i)
        try:
            if cap is None or not cap.isOpened():
                print(f"[{i}] 없음")
                continue
            ok, frame = False, None
            for _ in range(40):                      # 웹캠은 처음 몇십 장이 검게 나올 수 있음(자동 노출)
                ok, frame = cap.read()
                if ok and frame is not None and not is_dark(frame):
                    break
            if (not ok or frame is None or is_dark(frame)):
                cap.release()
                cap = _open(i, mjpg=False)          # MJPG 로 검게 나오는 웹캠 → 기본 형식으로 한 번 더
                for _ in range(40):
                    ok2, f2 = cap.read()
                    if ok2 and f2 is not None:
                        ok, frame = ok2, f2
                        if not is_dark(f2):
                            break
            if not ok or frame is None:
                print(f"[{i}] 열리지만 영상 없음(다른 프로그램이 사용 중일 수 있음)")
                continue
            h, w = frame.shape[:2]
            path = out / f"cam_{i}.jpg"
            cv2.imwrite(str(path), frame)
            found += 1
            level = int(frame.mean())
            note = "  ← 검은 화면: 렌즈 가림·다른 프로그램 사용 중·가상 카메라일 수 있음" if is_dark(frame) else ""
            if not is_dark(frame):
                bright.append(i)
            print(f"[{i}] 열림 {w}x{h} 밝기 {level} → 사진 {path.relative_to(ROOT)}{note}")
        finally:
            if cap is not None:
                cap.release()
    print(f"\n열린 카메라 {found}개, 영상이 보이는 번호 {bright or '없음'}.")
    if bright:
        print(f"상자 위 웹캠 번호를 .env 에 적으세요. 예) TOWER_KIOSK_CAMERAS=KIOSK-A={bright[0]}")
    if os.name == "nt":
        print("사진 폴더 열기: explorer data\\camera_check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
