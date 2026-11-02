"""정답지(answer key) 읽기·검사 — LF-15 (작성: 김건태·변재원).

한줄 설명: 사람이 엑셀로 적은 정답지 CSV를 채점기가 쓰는 모양으로 바꾸고, 데이터 누수·빠진 항목을 미리 잡아낸다.

CSV 칸 (evaluation/answer_key_template.csv 참고, 엑셀에서 "CSV UTF-8"로 저장)
    photo_file   촬영 파일 이름(예: wallet_W01_s3_002.jpg) — 물건 ID·세션을 여기서 읽음
    split        개선용 | 검증용 | 최종
    category     지갑 | USB | 립밤 | 모형폰
    항목마다 값 + 가시성 두 칸: color, color_vis, shape, shape_vis, mark, mark_vis,
                                visible_text, visible_text_vis, material, material_vis
    note         메모(채점에 안 씀)
가시성: 보임 | 안 보임 | 해당 없음
"""
from __future__ import annotations

import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import COLORS, FEATURE_FIELDS, UNKNOWN, VISIBILITY  # noqa: E402
from vision.config import CLASS_KO, parse_filename  # noqa: E402

SPLITS = ["개선용", "검증용", "최종"]
EXPECTED_PER_OBJECT = {"개선용": 3, "검증용": 1, "최종": 1}
COLUMNS = ["photo_file", "split", "category"] + [c for f in FEATURE_FIELDS for c in (f, f"{f}_vis")] + ["note"]


def load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:   # 엑셀 BOM 허용
        return [row for row in csv.DictReader(f) if any((v or "").strip() for v in row.values())]


def to_truths(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        info = parse_filename(r["photo_file"].strip()) or {}
        out.append({
            "photo_id": r["photo_file"].strip(), "split": r["split"].strip(), "category": r["category"].strip(),
            "object_id": info.get("object_id"), "session": info.get("session"),
            "fields": {f: {"value": (r.get(f) or "").strip(), "visibility": (r.get(f"{f}_vis") or "").strip()}
                       for f in FEATURE_FIELDS},
        })
    return out


def check(truths: list[dict]) -> tuple[list[str], list[str]]:
    """(오류, 경고). 오류가 하나라도 있으면 채점에 쓰지 않는다."""
    errs, warns = [], []
    seen = set()
    by_obj = defaultdict(lambda: defaultdict(list))   # 물건 → split → [세션]
    for t in truths:
        pid = t["photo_id"]
        if pid in seen:
            errs.append(f"{pid}: 같은 사진이 두 번 있음")
        seen.add(pid)
        info = parse_filename(pid)
        if not info:
            errs.append(f"{pid}: 파일 이름 규칙(품목_물건ID_세션_번호.jpg)에 맞지 않음")
            continue
        if CLASS_KO[info["category"]] != t["category"]:
            errs.append(f"{pid}: category '{t['category']}' 가 파일 이름 품목({CLASS_KO[info['category']]})과 다름")
        if t["split"] not in SPLITS:
            errs.append(f"{pid}: split 은 {SPLITS} 중 하나여야 함")
            continue
        by_obj[t["object_id"]][t["split"]].append(t["session"])
        for f, spec in t["fields"].items():
            vis, val = spec["visibility"], spec["value"]
            if vis not in VISIBILITY:
                errs.append(f"{pid}: {f}_vis '{vis}' 는 {VISIBILITY} 중 하나여야 함")
            elif vis == "보임" and val in ("", UNKNOWN):
                errs.append(f"{pid}: {f} 가 '보임'인데 정답 값이 비었음(없음이면 '없음'으로)")
            elif vis == "보임" and f == "color" and val not in COLORS:
                errs.append(f"{pid}: color '{val}' 가 색 목록에 없음")
    # 물건별 묶음: 장수, 세션 분리(같은 세션이 두 묶음에 있으면 데이터 누수)
    for obj, splits in sorted(by_obj.items()):
        for sp, n in EXPECTED_PER_OBJECT.items():
            if len(splits.get(sp, [])) != n:
                warns.append(f"{obj}: {sp} {len(splits.get(sp, []))}장 (권장 {n}장)")
        owner = {}
        for sp, sessions in splits.items():
            for s in set(sessions):
                if s in owner and owner[s] != sp:
                    errs.append(f"{obj}: 세션 {s} 가 {owner[s]}·{sp} 에 함께 있음(데이터 누수)")
                owner.setdefault(s, sp)
    # 검증용·최종 묶음 완비: 모든 품목 + 보임·안 보임 항목
    cats = {t["category"] for t in truths}
    for sp in ("검증용", "최종"):
        part = [t for t in truths if t["split"] == sp]
        if not part:
            warns.append(f"{sp} 묶음이 비었음")
            continue
        missing = cats - {t["category"] for t in part}
        if missing:
            errs.append(f"{sp} 묶음에 품목 {sorted(missing)} 이 없음(평가 불완전)")
        vis_kinds = {s["visibility"] for t in part for s in t["fields"].values()}
        for need in ("보임", "안 보임"):
            if need not in vis_kinds:
                errs.append(f"{sp} 묶음에 '{need}' 항목이 하나도 없음(평가 불완전)")
    return errs, warns


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="정답지 CSV 검사")
    ap.add_argument("csv", type=Path)
    a = ap.parse_args(argv)
    truths = to_truths(load(a.csv))
    errs, warns = check(truths)
    print(f"사진 {len(truths)}장 · 물건 {len({t['object_id'] for t in truths})}개")
    for sp in SPLITS:
        print(f"  {sp}: {sum(1 for t in truths if t['split'] == sp)}장")
    for w in warns:
        print("  ⚠️", w)
    for e in errs:
        print("  ❌", e)
    print("✅ 채점에 쓸 수 있음" if not errs else f"❌ 오류 {len(errs)}건 — 고친 뒤 다시 검사")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
