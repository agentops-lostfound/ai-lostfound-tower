"""웹캠 촬영 도구 (학습용·채점용 사진 모으기, LF-10).

한줄 설명: 키를 누를 때마다 파일 이름 규칙대로 사진을 저장하고, 사진마다 기록(CSV)을 남긴다.

사용법 (물건 하나씩)
    python vision/capture_images.py --category card_wallet --object W01 --session s1
조작
    스페이스: 한 장 저장 / a: 자동 연속 저장 켜기·끄기 / q 또는 Esc: 끝내기
시험용(화면 없이)
    python vision/capture_images.py --category card_wallet --object W01 --session s1 \
        --source 영상파일.mp4 --no-preview --auto-every 5 --max 20

- 화면의 안내 글자는 미리보기에만 그리고, 저장 사진에는 넣지 않는다.
- 같은 이름이 있으면 덮어쓰지 않고 다음 번호로 저장한다(예전 이름 사진 wallet_*·lipbalm_* 의 번호도 이어서 센다).
- 품목(6종, 11/6): card_wallet · usb · lip_balm · phone · hand_cream · power_bank
- 흐림 점수(라플라시안 분산)가 기준보다 낮으면 미리보기에 '흐림'을 표시한다.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from vision.config import CLASSES, make_filename, parse_filename, validate_names  # noqa: E402

CSV_FIELDS = ["filename", "category", "object_id", "session", "index", "captured_at", "width", "height", "blur", "brightness"]


def blur_score(frame: np.ndarray) -> float:
    """라플라시안 분산: 값이 작을수록 흐린 사진."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def brightness(frame: np.ndarray) -> float:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return float(gray.mean())


def next_index(out_dir: Path, category: str, object_id: str, session: str) -> int:
    """이미 저장된 같은 물건·세션 사진의 다음 번호."""
    last = -1
    if out_dir.is_dir():
        # 예전 이름 사진(wallet_W01_s1_*)도 같은 물건·세션으로 세어 번호가 겹치지 않게 한다(11/6 6종 고정)
        for p in out_dir.glob(f"*_{object_id}_{session}_*.jpg"):
            info = parse_filename(p.name)
            if info and info["category"] == category and info["object_id"] == object_id and info["session"] == session:
                last = max(last, info["index"])
    return last + 1


class Recorder:
    """사진 저장과 CSV 기록 담당 (카메라와 분리해서 시험하기 쉽게)."""

    def __init__(self, out_dir: Path, category: str, object_id: str, session: str, jpeg_quality: int = 95):
        validate_names(category, object_id, session)
        self.out_dir = out_dir
        self.category, self.object_id, self.session = category, object_id, session
        self.jpeg_quality = jpeg_quality
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = out_dir / "captures.csv"
        self.index = next_index(out_dir, category, object_id, session)
        self.saved = 0

    def save(self, frame: np.ndarray) -> Path:
        while True:  # 다른 창에서 같은 번호를 먼저 썼을 때도 덮어쓰지 않게
            name = make_filename(self.category, self.object_id, self.session, self.index)
            path = self.out_dir / name
            if not path.exists():
                break
            self.index += 1
        ok = cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            raise OSError(f"사진 저장 실패: {path}")
        h, w = frame.shape[:2]
        row = {
            "filename": name,
            "category": self.category,
            "object_id": self.object_id,
            "session": self.session,
            "index": self.index,
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "width": w,
            "height": h,
            "blur": round(blur_score(frame), 1),
            "brightness": round(brightness(frame), 1),
        }
        new_file = not self.csv_path.exists()
        with self.csv_path.open("a", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        self.index += 1
        self.saved += 1
        return path


def draw_overlay(frame: np.ndarray, rec: Recorder, auto: bool, blur: float, blur_min: float) -> np.ndarray:
    view = frame.copy()
    lines = [
        f"{rec.category} {rec.object_id} {rec.session}  saved={rec.saved}  next={rec.index:03d}",
        "SPACE save | a auto " + ("ON" if auto else "off") + " | q quit",
    ]
    color = (0, 255, 0)
    if blur < blur_min:
        lines.append(f"BLUR {blur:.0f} < {blur_min:.0f}")
        color = (0, 0, 255)
    for i, text in enumerate(lines):
        cv2.putText(view, text, (12, 30 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(view, text, (12, 30 + 28 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    return view


def open_source(source: str, width: int, height: int) -> cv2.VideoCapture:
    if source.isdigit():
        # Windows에서는 DirectShow가 해상도 설정을 잘 따른다(추정). 다른 OS는 기본 백엔드
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        cap = cv2.VideoCapture(int(source), backend)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    else:
        cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"카메라/영상을 열 수 없습니다: {source} (번호를 0, 1, 2로 바꿔 보세요)")
    return cap


def run(args: argparse.Namespace) -> int:
    rec = Recorder(args.out / args.session, args.category, args.object, args.session)
    cap = open_source(args.source, args.width, args.height)
    auto = args.auto_every > 0
    # a 키로 켰을 때 기본 간격 15프레임(30fps 카메라에서 약 0.5초)
    every = args.auto_every if args.auto_every > 0 else 15
    frame_no = 0
    print(f"저장 위치: {rec.out_dir} (다음 번호 {rec.index:03d})")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("더 이상 프레임이 없습니다(카메라 연결 또는 영상 끝).")
                break
            frame_no += 1
            score = blur_score(frame)
            key = -1
            if not args.no_preview:
                cv2.imshow("capture", draw_overlay(frame, rec, auto, score, args.blur_min))
                key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("a"):
                auto = not auto
            want = key == ord(" ") or (auto and frame_no % every == 0)
            if want:
                if args.skip_blurry and score < args.blur_min:
                    print(f"흐린 사진 건너뜀 (blur={score:.0f})")
                else:
                    path = rec.save(frame)
                    print(f"저장: {path.name}  blur={score:.0f}")
            if args.max and rec.saved >= args.max:
                print(f"최대 {args.max}장 저장, 종료")
                break
            if args.no_preview and args.source.isdigit():
                time.sleep(0.01)
    finally:
        cap.release()
        if not args.no_preview:
            cv2.destroyAllWindows()
    print(f"이번에 저장한 사진: {rec.saved}장 · 기록: {rec.csv_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="분실물 사진 촬영 도구")
    ap.add_argument("--category", required=True, choices=CLASSES, help="품목")
    ap.add_argument("--object", required=True, help="물건 ID (예: W01)")
    ap.add_argument("--session", required=True, help="세션 (예: s1)")
    ap.add_argument("--out", type=Path, default=Path("datasets/raw"), help="저장 폴더 (세션별 하위 폴더가 생김)")
    ap.add_argument("--source", default="0", help="카메라 번호 또는 영상 파일 경로")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--auto-every", type=int, default=0, help="자동 저장 간격(프레임). 0이면 끔")
    ap.add_argument("--max", type=int, default=0, help="이만큼 저장하면 종료. 0이면 제한 없음")
    ap.add_argument("--blur-min", type=float, default=100.0, help="이보다 흐림 점수가 낮으면 '흐림' 표시")
    ap.add_argument("--skip-blurry", action="store_true", help="흐린 사진은 저장하지 않음")
    ap.add_argument("--no-preview", action="store_true", help="화면 없이 실행(시험·자동 저장용)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_names(args.category, args.object, args.session)
    except ValueError as e:
        raise SystemExit(str(e))
    if args.no_preview and args.auto_every <= 0:
        raise SystemExit("--no-preview 에서는 키를 누를 수 없으니 --auto-every 를 함께 지정하세요")
    if args.no_preview and args.source.isdigit() and args.max <= 0:
        raise SystemExit("화면 없이 카메라로 찍을 때는 --max 로 장수를 정하세요(끝없이 저장되는 것 방지)")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
