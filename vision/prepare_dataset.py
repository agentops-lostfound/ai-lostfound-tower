"""라벨링 결과를 YOLO 학습 폴더로 정리 (세션 단위 분할, LF-10).

한줄 설명: Label Studio에서 내보낸 사진·라벨을 학습(train)과 검증(val)으로 나누고 data.yaml을 만든다.

입력 (Label Studio → Export → YOLO 형식을 푼 폴더)
    export/images/*.jpg
    export/labels/*.txt
    export/classes.txt
사용법
    python vision/prepare_dataset.py --export D:/ls_export --val-sessions s2 --out datasets/vision_v1103

- 같은 세션 사진이 train과 val에 섞이지 않게 세션 단위로 나눈다(데이터 누수 방지).
- classes.txt 순서가 우리 순서(config.CLASSES)와 달라도 이름으로 맞춰 번호를 다시 매긴다.
- Label Studio가 파일 이름 앞에 붙이는 'a1b2c3d4-' 같은 접두어를 떼고 원래 이름으로 저장한다.
- 라벨 파일이 없는 사진은 '빈 배경'으로 보고 빈 라벨을 만든다.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.config import CLASSES, parse_filename  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png"}


def original_name(name: str) -> str:
    """'3f2a9c1e-wallet_W01_s1_001.jpg' → 'wallet_W01_s1_001.jpg' (접두어가 없으면 그대로)."""
    if parse_filename(name):
        return name
    if "-" in name:
        rest = name.split("-", 1)[1]
        if parse_filename(rest):
            return rest
    return name


def class_remap(classes_txt: Path) -> dict[int, int]:
    names = [n.strip() for n in classes_txt.read_text(encoding="utf-8-sig").splitlines() if n.strip()]
    remap: dict[int, int] = {}
    for i, n in enumerate(names):
        if n not in CLASSES:
            raise SystemExit(f"classes.txt 에 모르는 품목 이름이 있습니다: {n!r} (허용: {CLASSES})")
        remap[i] = CLASSES.index(n)
    return remap


def convert_label(text: str, remap: dict[int, int], src: str) -> tuple[str, list[int]]:
    out_lines, cls_list = [], []
    for ln, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 5:
            raise ValueError(f"{src}:{ln} 박스 라벨은 값 5개(클래스 x y w h)여야 합니다")
        cid = int(parts[0])
        if cid not in remap:
            raise ValueError(f"{src}:{ln} classes.txt 에 없는 클래스 번호 {cid}")
        coords = [float(v) for v in parts[1:]]
        if not all(0.0 <= v <= 1.0 for v in coords):
            raise ValueError(f"{src}:{ln} 좌표는 0~1 사이여야 합니다")
        new = remap[cid]
        cls_list.append(new)
        out_lines.append(" ".join([str(new)] + parts[1:]))
    return ("\n".join(out_lines) + ("\n" if out_lines else "")), cls_list


def prepare(export: Path, out: Path, val_sessions: set[str]) -> dict:
    img_dir, lbl_dir, cls_txt = export / "images", export / "labels", export / "classes.txt"
    for p in (img_dir, cls_txt):
        if not p.exists():
            raise SystemExit(f"내보내기 폴더에 {p.name} 이(가) 없습니다: {p}")
    remap = class_remap(cls_txt)
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"출력 폴더가 비어 있지 않습니다(덮어쓰기 방지): {out}")

    # 1차: 모든 사진·라벨을 먼저 검사한다(오류가 있으면 출력 폴더를 만들지 않음)
    stats = {"train": Counter(), "val": Counter()}
    images = {"train": 0, "val": 0}
    skipped: list[str] = []
    sessions_seen: set[str] = set()
    plan: list[tuple[Path, str, str, str]] = []  # (원본 사진, 원래 이름, split, 라벨 내용)
    for img in sorted(img_dir.iterdir()):
        if img.suffix.lower() not in IMG_EXT:
            continue
        name = original_name(img.name)
        info = parse_filename(name)
        if not info:
            skipped.append(img.name)
            continue
        sessions_seen.add(info["session"])
        split = "val" if info["session"] in val_sessions else "train"
        lbl_src = lbl_dir / (img.stem + ".txt")
        text = lbl_src.read_text(encoding="utf-8") if lbl_src.exists() else ""
        label_text, cls_list = convert_label(text, remap, lbl_src.name)
        plan.append((img, name, split, label_text))
        images[split] += 1
        stats[split].update(CLASSES[c] for c in cls_list)

    if images["train"] == 0 or images["val"] == 0:
        raise SystemExit(f"train {images['train']}장 / val {images['val']}장 — 한쪽이 비었습니다. --val-sessions 를 확인하세요 (있는 세션: {sorted(sessions_seen)})")

    # 2차: 검사를 통과하면 복사
    for img, name, split, label_text in plan:
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, out / "images" / split / name)
        (out / "labels" / split / (Path(name).stem + ".txt")).write_text(label_text, encoding="utf-8")

    yaml_text = "path: .\ntrain: images/train\nval: images/val\nnames:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES))
    (out / "data.yaml").write_text(yaml_text, encoding="utf-8")
    return {"images": images, "boxes": {k: dict(v) for k, v in stats.items()}, "skipped": skipped, "sessions": sorted(sessions_seen)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Label Studio YOLO 내보내기 → 학습 폴더")
    ap.add_argument("--export", type=Path, required=True, help="Label Studio 내보내기를 푼 폴더")
    ap.add_argument("--out", type=Path, required=True, help="만들 학습 폴더 (예: datasets/vision_v1103)")
    ap.add_argument("--val-sessions", required=True, help="검증으로 쓸 세션, 쉼표로 여러 개 (예: s2 또는 s2,s4)")
    a = ap.parse_args(argv)
    val = {s.strip() for s in a.val_sessions.split(",") if s.strip()}
    r = prepare(a.export, a.out, val)
    print(f"완료: {a.out}")
    print(f"  사진  train {r['images']['train']}장 / val {r['images']['val']}장 (세션 {r['sessions']})")
    for split in ("train", "val"):
        print(f"  박스  {split}: " + ", ".join(f"{c} {r['boxes'][split].get(c, 0)}" for c in CLASSES))
    if r["skipped"]:
        print(f"  파일 이름 규칙에 안 맞아 건너뜀 {len(r['skipped'])}장: {r['skipped'][:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
