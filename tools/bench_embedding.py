"""텍스트 임베딩 모델 실측 — 매칭 ①(분실인 말 ↔ 물건 특징) 모델 고르기 (architecture.md 3-3).

한줄 설명: 다국어 임베딩 모델을 이 PC에서 직접 돌려 "모델 읽기 시간·문장 1개 시간·메모리·한영 비교가 맞는지"를 표로 보여 준다.

준비(처음 한 번, 저장소 폴더 .venv) — CPU 판 torch 가 함께 깔려 약 1GB 이상 내려받는다(추정)
    pip install sentence-transformers psutil
사용법
    python tools/bench_embedding.py                          # 기본 후보 2개, CPU
    python tools/bench_embedding.py --models intfloat/multilingual-e5-small --device cpu --n 200

- GPU 는 쓰지 않는 것이 기본이다(Qwen·VLA 와 GPU 를 나눠 쓰지 않기 위해, 3-4장). --device cuda 는 비교용으로만
- 처음 실행 때 모델을 인터넷에서 받는다(Hugging Face). 받은 뒤에는 캐시에서 읽는다
- 결과 판단: "같은 물건" 쌍의 점수가 "다른 물건" 쌍보다 확실히 높고(차이), 문장 1개 시간이 수십 ms 이하이면 후보
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from typing import Callable

DEFAULT_MODELS = ["intfloat/multilingual-e5-small", "BAAI/bge-m3"]

# (분실인 말, 물건 특징 문장(Qwen 영어), 같은 물건인가)
PAIRS = [
    ("붉은 주황색 반지갑이고 앞에 별 모양 스티커가 있어요", "red bifold wallet, leather, star sticker on front corner", True),
    ("검은색 휴대폰, 뒷면에 ABC 라고 적혀 있어요", "black rectangle phone, text ABC on back", True),
    ("갈색 가죽 카드지갑, 모서리가 조금 긁혔어요", "brown card wallet, leather, scratch on corner", True),
    ("하얀 립밤, 뚜껑이 파란색", "white lip balm with blue cap", True),
    ("붉은 주황색 반지갑이고 앞에 별 모양 스티커가 있어요", "black rectangle phone, text ABC on back", False),
    ("검은색 휴대폰, 뒷면에 ABC 라고 적혀 있어요", "white lip balm with blue cap", False),
    ("갈색 가죽 카드지갑, 모서리가 조금 긁혔어요", "red bifold wallet, leather, star sticker on front corner", False),
    ("하얀 립밤, 뚜껑이 파란색", "brown card wallet, leather, scratch on corner", False),
]


def prefixed(model_name: str, text: str, kind: str) -> str:
    """e5 계열은 앞말이 필요하다(query: 질문 / passage: 문서)."""
    if "e5" in model_name.lower():
        return f"{'query' if kind == 'q' else 'passage'}: {text}"
    return text


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def bench(model_name: str, load: Callable[[str], object], n: int = 100) -> dict:
    """load(model_name) → .encode(list[str]) 를 가진 모델. 결과: 읽기 초·문장당 ms·같은/다른 쌍 점수."""
    t0 = time.perf_counter()
    model = load(model_name)
    load_s = time.perf_counter() - t0
    q = prefixed(model_name, PAIRS[0][0], "q")
    model.encode([q])                                  # 첫 실행(준비) 시간은 빼고 잰다
    times = []
    for _ in range(n):
        t = time.perf_counter()
        model.encode([q])
        times.append((time.perf_counter() - t) * 1000)
    same, diff = [], []
    for ko, en, is_same in PAIRS:
        a, b = model.encode([prefixed(model_name, ko, "q"), prefixed(model_name, en, "p")])
        (same if is_same else diff).append(cosine(list(a), list(b)))
    return {"model": model_name, "load_s": load_s, "ms_median": statistics.median(times),
            "ms_p95": sorted(times)[max(0, int(len(times) * 0.95) - 1)],
            "same_min": min(same), "diff_max": max(diff), "gap": min(same) - max(diff)}


def _rss_mb() -> float | None:
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="다국어 텍스트 임베딩 모델 실측")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--n", type=int, default=100, help="문장 1개 시간 반복 횟수")
    a = ap.parse_args(argv)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers 가 없습니다 → pip install sentence-transformers psutil")
        return 1
    print(f"장치: {a.device} · 반복 {a.n}회 · 쌍 {len(PAIRS)}개(같은 물건 {sum(p[2] for p in PAIRS)}개)")
    print("모델 | 읽기(초) | 문장1개 중앙(ms) | p95(ms) | 같은물건 최저 | 다른물건 최고 | 차이 | 메모리(MB)")
    for name in a.models:
        before = _rss_mb()
        try:
            r = bench(name, lambda m: SentenceTransformer(m, device=a.device), a.n)
        except Exception as e:
            print(f"{name} | 실패({type(e).__name__}: {str(e)[:80]})")
            continue
        after = _rss_mb()
        mem = f"{after - before:.0f}" if before is not None and after is not None else "?"
        print(f"{r['model']} | {r['load_s']:.1f} | {r['ms_median']:.1f} | {r['ms_p95']:.1f} | "
              f"{r['same_min']:.3f} | {r['diff_max']:.3f} | {r['gap']:+.3f} | {mem}")
    print("판단: 차이가 0보다 충분히 크고(+0.05 이상 권장, 추정) 문장1개가 수십 ms 이하인 모델을 고른다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
