"""AI 자기 개선 회차 — LF-15.

한줄 설명: 채점 → 틀린 이유 분석 → 개선안 2개 시험 → 검증 사진으로 채택 판정 → 기록을 반복해, AI가 스스로 오차를 줄이게 한다.

규칙 (docs/agent-scoring.md 6장)
- 개선안 하나에는 **바꾸는 것 하나만**(무엇 때문에 좋아졌는지 알 수 있게)
- 개선안을 만드는 쪽(proposer)은 **개선용 사진의 오차만** 본다. 검증용 사진·정답은 보여 주지 않는다
- 채택은 코드가 정한다(scoring.should_adopt): 3점 이상 상승 · C·P 하락 없음 · 지어낸 특징 비율 증가 없음 · p95 한도 안 · 평가군 완비
- 멈춤: 목표 점수 도달, 3회 연속 채택 실패, 또는 최대 회차
- 바꿀 수 있는 것은 아래 TOOLS 의 범위뿐. 정답지·배점·채점 코드·데이터 분할은 바꿀 방법 자체가 없다

실행(가짜 비전으로 흐름 연습)
    python evaluation/improve_loop.py --demo --p95-limit 3            # 연습용 가짜 정답지 70장
진짜 비전이 나오면 runner(config, split) 를 김건태 님 비전 실행 함수로 바꾼다.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import FEATURE_FIELDS, UNKNOWN  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402
from evaluation import answer_key  # noqa: E402
from evaluation.eval_vision import mistakes as find_mistakes  # noqa: E402
from evaluation.scoring import grade, should_adopt, vision_score  # noqa: E402

# ---------- 개선 도구: 바꿀 수 있는 설정과 허용 범위 ----------
PROMPTS = ["v1", "v2-hold-strict", "v3-mark-focus"]        # 등록된 특징 추출 지침
MODELS = ["qwen3-vl:4b-instruct", "qwen3-vl:2b"]             # 미리 준비한 모델
OCR_PRESETS = ["default", "binarize", "upscale"]

TOOLS = {
    "set_crop_config": {"key": "crop_margin", "range": (0.0, 0.3)},
    "set_feature_prompt": {"key": "prompt_version", "choices": PROMPTS},
    "set_ocr_config": {"key": "ocr_preset", "choices": OCR_PRESETS},
    "select_model": {"key": "model", "choices": MODELS},
    "set_threshold": {"key": "conf_threshold", "range": (0.3, 0.9)},
}
DEFAULT_CONFIG = {"crop_margin": 0.05, "prompt_version": "v1", "ocr_preset": "default",
                  "model": "qwen3-vl:4b-instruct", "conf_threshold": 0.5}


def apply_change(config: dict, tool: str, value) -> dict:
    """허용 범위 안에서 설정 하나만 바꾼 새 설정을 돌려준다. 범위를 벗어나면 ValueError."""
    if tool not in TOOLS:
        raise ValueError(f"쓸 수 없는 도구: {tool} (허용: {list(TOOLS)})")
    spec = TOOLS[tool]
    if "range" in spec:
        lo, hi = spec["range"]
        if not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ValueError(f"{tool}: {value!r} 는 {lo}~{hi} 범위 밖")
    elif value not in spec["choices"]:
        raise ValueError(f"{tool}: {value!r} 는 등록된 값({spec['choices']})이 아님")
    new = dict(config)
    new[spec["key"]] = value
    return new


def changed_keys(a: dict, b: dict) -> list[str]:
    return [k for k in set(a) | set(b) if a.get(k) != b.get(k)]


# ---------- 개선안 만들기(규칙 기반, 나중에 LLM으로 바꿀 수 있음) ----------
def rule_proposer(config: dict, result: dict, mistakes: list[str], tried: set) -> list[dict]:
    """개선용 오차 목록만 보고 개선안 2개를 만든다. 이미 시도한 (도구, 값)은 다시 내지 않는다."""
    fabricated = sum("지어냄" in m for m in mistakes)
    missed = sum("놓침" in m for m in mistakes)
    wrong_cat = sum("품목" in m for m in mistakes)
    ideas = []
    if fabricated:
        ideas.append(("set_feature_prompt", "v2-hold-strict", f"안 보이는 특징을 지어냄 {fabricated}건 → 보류를 강조한 지침"))
    if missed:
        ideas.append(("set_crop_config", min(0.3, round(config["crop_margin"] + 0.1, 2)), f"보이는 특징 놓침 {missed}건 → 자르기 여백 넓힘"))
    if any("mark" in m for m in mistakes):
        ideas.append(("set_feature_prompt", "v3-mark-focus", "스티커·흠집(mark) 오답 → 표시를 먼저 찾게 하는 지침"))
    if any("visible_text" in m for m in mistakes):
        ideas.append(("set_ocr_config", "upscale", "겉 글자 오답 → 글자 영역 확대 후 OCR"))
    if wrong_cat:
        ideas.append(("set_threshold", 0.7, f"품목 오답 {wrong_cat}건 → 확신 낮으면 보류"))
    ideas.append(("set_crop_config", max(0.0, round(config["crop_margin"] - 0.05, 2)), "배경이 섞였을 수 있음 → 여백 줄임"))
    out = []
    for tool, value, why in ideas:
        if (tool, value) in tried or apply_change(config, tool, value) == config:
            continue
        out.append({"tool": tool, "value": value, "reason": why})
        if len(out) == 2:
            break
    return out


# ---------- 가짜 비전(흐름 연습·시험용) ----------
def _roll(*parts) -> float:
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def simulated_runner(truths: list[dict]) -> Callable[[dict, str], tuple[dict, float]]:
    """설정에 따라 오답 확률이 달라지는 가짜 비전. 같은 설정이면 항상 같은 답(결정적)."""
    def run(config: dict, split: str) -> tuple[dict, float]:
        fab = {"v1": 0.45, "v2-hold-strict": 0.1, "v3-mark-focus": 0.3}[config["prompt_version"]]
        miss = max(0.05, 0.35 - config["crop_margin"])
        wrong = 0.25 if config["prompt_version"] == "v1" else 0.12
        preds = {}
        for t in truths:
            if t["split"] != split:
                continue
            p = {"category": t["category"]}
            for f in FEATURE_FIELDS:
                spec = t["fields"][f]
                r = _roll(t["photo_id"], f, config["prompt_version"], config["crop_margin"])
                if spec["visibility"] == "보임":
                    p[f] = UNKNOWN if r < miss else ("다른 값" if r < miss + wrong else spec["value"])
                else:
                    p[f] = "지어낸 값" if r < fab else UNKNOWN
            preds[t["photo_id"]] = p
        p95 = 1.5 + config["crop_margin"] * 2 + (0.8 if config["ocr_preset"] == "upscale" else 0.0)
        return preds, round(p95, 2)
    return run


def demo_truths(n_objects: int = 14) -> list[dict]:
    """연습용 가짜 정답지: 지갑 n개 × 5장(개선용 3·검증용 1·최종 1, 세션 분리). 실제 정답지(약 70장)와 같은 크기."""
    colors = ["검정", "갈색", "빨강", "남색", "회색", "흰색", "초록"]
    shapes = ["반지갑", "장지갑", "카드지갑"]
    plan = [("개선용", "s3", 0), ("개선용", "s3", 1), ("개선용", "s3", 2), ("검증용", "s4", 0), ("최종", "s5", 0)]
    out = []
    for i in range(n_objects):
        oid = f"W{i + 1:02d}"
        base = {"color": colors[i % len(colors)], "shape": shapes[i % len(shapes)],
                "mark": "별 스티커" if i % 2 else "없음", "visible_text": "ABC" if i % 3 == 0 else "없음", "material": "가죽"}
        for sp, ses, k in plan:
            fields = {f: {"value": v, "visibility": "보임"} for f, v in base.items()}
            fields["material"] = {"value": "", "visibility": "안 보임"}          # 재질은 사진으로 판단 어려움
            if (i + k) % 4 == 0:
                fields["mark"] = {"value": "", "visibility": "안 보임"}          # 가끔 스티커 면이 안 보임
            out.append({"photo_id": f"wallet_{oid}_{ses}_{k:03d}.jpg", "split": sp, "category": "지갑",
                        "object_id": oid, "session": ses, "fields": fields})
    return out


# ---------- 회차 실행 ----------
@dataclass
class LoopState:
    config: dict
    round_no: int = 0
    fails_in_row: int = 0
    tried: set = field(default_factory=set)
    history: list[dict] = field(default_factory=list)
    stop_reason: str = ""


def evaluate(runner, config: dict, truths: list[dict], split: str) -> dict:
    part = [t for t in truths if t["split"] == split]
    preds, p95 = runner(config, split)
    r = vision_score(preds, part)
    r["p95"] = p95
    r["mistakes"] = find_mistakes(preds, part)
    return r


def run_round(st: LoopState, truths, runner, proposer, p95_limit, eval_complete, reporter: Reporter) -> dict:
    st.round_no += 1
    base = evaluate(runner, st.config, truths, "개선용")
    # 개선안을 만드는 쪽에는 개선용 오차만 넘긴다
    proposals = proposer(st.config, {k: base[k] for k in ("score", "C", "P", "R", "A")}, list(base["mistakes"]), st.tried)
    log = {"round": st.round_no, "base_config": dict(st.config), "base_score": base["score"], "proposals": [], "adopted": False}
    if not proposals:
        log["result"] = "개선안 없음"
        st.history.append(log)
        st.stop_reason = "더 시도할 개선안이 없음"
        return log
    best = None
    for pr in proposals:
        cand_cfg = apply_change(st.config, pr["tool"], pr["value"])
        if len(changed_keys(st.config, cand_cfg)) != 1:   # python -O 에서도 꺼지지 않게 assert 대신 직접 검사
            raise ValueError("개선안은 바꾸는 것 하나만")
        st.tried.add((pr["tool"], pr["value"]))
        r = evaluate(runner, cand_cfg, truths, "개선용")
        log["proposals"].append({**pr, "improve_score": r["score"]})
        if best is None or r["score"] > best[1]["score"]:
            best = (cand_cfg, r, pr)
    cand_cfg, _, pr = best
    base_val = evaluate(runner, st.config, truths, "검증용")
    cand_val = evaluate(runner, cand_cfg, truths, "검증용")
    ok, checks = should_adopt(base_val, cand_val, p95_limit, eval_complete)
    log.update({"chosen": pr, "val_base": base_val["score"], "val_cand": cand_val["score"], "checks": checks, "adopted": ok,
                "val_metrics": {k: cand_val[k] for k in ("C", "P", "R", "A", "fabricated_rate", "p95")}})
    if ok:
        st.config = cand_cfg
        st.fails_in_row = 0
        st.tried = set()   # 기준 설정이 바뀌었으니 예전에 진 개선안도 다시 시도할 수 있다
    else:
        st.fails_in_row += 1
    st.history.append(log)
    mark = "✅ 채택" if ok else "✖ 거절"
    failed = [k for k, v in checks.items() if not v]
    reporter.score(f"{st.round_no}회차 {mark}",
                   f"개선안: {pr['tool']} = {pr['value']} ({pr['reason']})\n"
                   f"검증용 비전 {base_val['score']} → {cand_val['score']} ({grade(cand_val['score'])})"
                   + (f"\n통과 못 한 조건: {', '.join(failed)}" if failed else ""))
    return log


def run_loop(truths, runner, proposer=rule_proposer, config=None, target=80.0, max_rounds=5,
             p95_limit: float | None = None, reporter: Reporter | None = None, log_path: Path | None = None) -> LoopState:
    reporter = reporter or Reporter()
    errs, _ = answer_key.check(truths)
    eval_complete = not errs
    st = LoopState(config=dict(config or DEFAULT_CONFIG))
    while st.round_no < max_rounds:
        run_round(st, truths, runner, proposer, p95_limit, eval_complete, reporter)
        if st.stop_reason:
            break
        cur = evaluate(runner, st.config, truths, "검증용")["score"]
        if cur >= target:
            st.stop_reason = f"목표 {target}점 도달(검증용 {cur})"
            break
        if st.fails_in_row >= 3:
            st.stop_reason = "3회 연속 채택 실패"
            break
    else:
        st.stop_reason = st.stop_reason or f"최대 {max_rounds}회차"
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            for h in st.history:
                f.write(json.dumps(h, ensure_ascii=False, default=str) + "\n")
    return st


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI 자기 개선 회차")
    ap.add_argument("--key", type=Path, default=None, help="정답지 CSV(--demo 에서 빼면 연습용 가짜 정답지 70장 사용)")
    ap.add_argument("--demo", action="store_true", help="가짜 비전으로 실행(진짜 비전 연결 전 연습)")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--target", type=float, default=80.0)
    ap.add_argument("--p95-limit", type=float, default=None, help="처리 시간 한도(초). 정하지 않으면 자동 채택 안 함")
    ap.add_argument("--send", action="store_true", help="회차 결과를 #📈평가-점수로 전송")
    ap.add_argument("--log", type=Path, default=Path("runs/improve_rounds.jsonl"))
    a = ap.parse_args(argv)
    if not a.demo and a.key is None:
        raise SystemExit("--key 정답지 CSV 가 필요합니다")
    truths = answer_key.to_truths(answer_key.load(a.key)) if a.key else demo_truths()
    if not a.demo:
        raise SystemExit("진짜 비전 실행 함수가 아직 없습니다(LF-3). 지금은 --demo 로 흐름을 연습하세요")
    rep = Reporter(dry_run=not a.send)
    st = run_loop(truths, simulated_runner(truths), target=a.target, max_rounds=a.rounds,
                  p95_limit=a.p95_limit, reporter=rep, log_path=a.log)
    for h in st.history:
        if "chosen" in h:
            print(f"{h['round']}회차 {'✅ 채택' if h['adopted'] else '✖ 거절'}: {h['chosen']['tool']}={h['chosen']['value']} "
                  f"· 검증용 {h['val_base']} → {h['val_cand']}")
        else:
            print(f"{h['round']}회차: {h.get('result')}")
    print(f"멈춤: {st.stop_reason} · 최종 설정 {st.config}")
    print(f"기록: {a.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
