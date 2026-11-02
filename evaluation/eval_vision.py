"""비전 채점 실행기 — LF-15.

한줄 설명: 비전 결과 파일과 정답지를 넣으면 묶음(개선용·검증용·최종)별 비전 점수와 틀린 사진 목록을 낸다.

사용법
    python evaluation/eval_vision.py --key answer_key.csv --preds preds.json --split 개선용
    python evaluation/eval_vision.py --key answer_key.csv --preds preds.json --split 최종 --final   # 발표 직전 한 번만
preds.json: {"wallet_W01_s3_002.jpg": {"category": "지갑", "color": "검정", ...}, ...}

- 정답지에 오류가 있으면 채점하지 않는다.
- '최종' 묶음은 --final 을 붙여야만 채점한다(보고 다시 고치면 데이터 누수).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import FEATURE_FIELDS  # noqa: E402
from discord_ops.reporter import Reporter, format_scoreboard  # noqa: E402
from evaluation import answer_key  # noqa: E402
from evaluation.scoring import grade, is_hold, norm, vision_score  # noqa: E402


def mistakes(preds: dict, truths: list[dict]) -> list[str]:
    """틀린 이유를 항목·유형별로(개선 에이전트가 볼 오차 목록)."""
    out = []
    for t in truths:
        p = preds.get(t["photo_id"], {})
        if norm(p.get("category")) != norm(t["category"]):
            out.append(f"{t['photo_id']}: 품목 {t['category']} → {p.get('category', '없음')}")
        for f in FEATURE_FIELDS:
            spec = t["fields"][f]
            ans = p.get(f)
            if spec["visibility"] == "보임" and is_hold(ans):
                out.append(f"{t['photo_id']}: {f} 놓침")
            elif spec["visibility"] == "보임" and norm(ans) != norm(spec["value"]):
                out.append(f"{t['photo_id']}: {f} 오답 '{ans}' (정답 '{spec['value']}')")
            elif spec["visibility"] == "안 보임" and not is_hold(ans):
                out.append(f"{t['photo_id']}: {f} 지어냄 '{ans}'")
    return out


def run(key: Path, preds_path: Path, split: str, final: bool = False) -> dict:
    if split == "최종" and not final:
        raise SystemExit("'최종' 묶음은 발표 직전 한 번만 씁니다. 정말이면 --final 을 붙이세요")
    truths = answer_key.to_truths(answer_key.load(key))
    errs, _ = answer_key.check(truths)
    if errs:
        raise SystemExit(f"정답지 오류 {len(errs)}건 — 먼저 `python evaluation/answer_key.py {key}` 로 고치세요")
    part = [t for t in truths if t["split"] == split]
    if not part:
        raise SystemExit(f"{split} 묶음 사진이 없습니다")
    preds = json.loads(preds_path.read_text(encoding="utf-8"))
    r = vision_score(preds, part)
    r["mistakes"] = mistakes(preds, part)
    r["split"] = split
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="비전 채점")
    ap.add_argument("--key", type=Path, required=True)
    ap.add_argument("--preds", type=Path, required=True)
    ap.add_argument("--split", choices=answer_key.SPLITS, default="개선용")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--send", action="store_true", help="#📈평가-점수로 전송")
    a = ap.parse_args(argv)
    r = run(a.key, a.preds, a.split, a.final)
    print(f"[{r['split']}] 비전 {r['score']}점({grade(r['score'])}) · C {r['C']} · P {r['P']} · R {r['R']} · A {r['A']} · "
          f"지어낸 특징 {r['fabricated_rate']:.0%} · 사진 {r['photos']}장")
    for m in r["mistakes"][:30]:
        print("  -", m)
    if len(r["mistakes"]) > 30:
        print(f"  … 외 {len(r['mistakes']) - 30}건")
    title, body = format_scoreboard(a.round, {"비전": r["score"]},
                                    extra=f"{r['split']} {r['photos']}장 · C {r['C']} · P {r['P']} · R {r['R']} · A {r['A']} · 오류 {len(r['mistakes'])}건")
    Reporter(dry_run=not a.send).score(title, body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
