"""교육원 관제탑 PC(RTX 3050 6GB) 그래픽카드 메모리 가상 시뮬레이션 (11/8 변재원).

한줄 설명: 시연 1시간 동안 챗봇 질문·키오스크 사진·반환(메인 AI·로봇 VLA)이 무작위로 겹칠 때
6GB 그래픽카드 메모리가 넘치는지(= 프로그램이 죽거나 로봇이 멈추는지) 수천 번 돌려 보는 계산기.

실행(저장소 폴더, 아무 가상환경):
    python tools/gpu_budget_sim.py                 # 지금 방식(policy=now) vs 고친 방식(policy=lease) 비교
    python tools/gpu_budget_sim.py --runs 2000 --display 1300 --vla 3000   # 나쁜 쪽 전제로

전제(PREMISES) — 숫자 출처를 같이 적는다. (추정)은 실측 전, TBD 는 모르는 값
- 그래픽카드 6144MiB, 여유 300MiB 는 늘 남겨 둔다(Windows WDDM·조각화, 추정)
- 화면(모니터가 3050 에 꽂힘): 700~1300MiB (docs/ollama/README.md "약 1GB", 집 PC 1216MiB 실측)
- Mi:dm 2.0 Mini(Ollama, num_ctx 4096): 2100~2400MiB — 집 PC 11/8 실측(두 모델 합 4844MiB − Qwen 쪽)에서 계산
- Qwen3-VL-2B NF4 작업자(파이썬 프로세스 전체): 2300~2700MiB — 집 PC 실측 peak reserved 2298MiB + CUDA 기본(추정 300~400)
- SmolVLA 집기(관제탑이 vla 사용권을 받는 동안): 1500~3000MiB (추정, TBD — LF-19 실측 전. 450M 매개변수 기준)
- Ollama 는 메모리가 모자라면 일부를 CPU 로 돌려 '느려질' 뿐 죽지 않는다. PyTorch(Qwen·VLA)는 모자라면 OOM 으로 실패
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field

TOTAL, MARGIN = 6144, 300


@dataclass
class Premise:
    display: tuple = (700, 1300)
    midm: tuple = (2100, 2400)
    qwen: tuple = (2300, 2700)
    vla: tuple = (1500, 3000)
    chat_per_min: tuple = (0.5, 3.0)      # 웹·키오스크 AI 안내·디스코드 질문(시연 중, 추정)
    photo_per_min: tuple = (0.1, 0.5)     # 키오스크 사진 접수
    return_per_min: tuple = (0.05, 0.3)   # 반환(로봇)
    uncertain: float = 0.3                # 매칭이 애매해 메인 AI(Mi:dm)를 부르는 비율(추정)
    minutes: int = 60


@dataclass
class Result:
    oom_qwen: int = 0          # 사진 분석 실패(직원 확인)
    oom_vla: int = 0           # 로봇 집기 실패(정지·직원 확인)
    slow_chat: int = 0         # Mi:dm 이 일부 CPU 로 → 답 느림
    cpu_chat: int = 0          # 고친 방식: 사용권 중이라 CPU 로 답함(느리지만 정상)
    gpu_wait_fail: int = 0     # 사용권을 60초 안에 못 받음 → 직원 확인
    busy: int = 0              # 반환 중이라 다음 반환을 '잠시 후'로 미룸(두 방식 같음)
    peak: int = 0
    events: dict = field(default_factory=lambda: {"chat": 0, "photo": 0, "return": 0})


def _draw(rng, r):
    return rng.uniform(*r)


def simulate(policy: str, p: Premise, seed: int) -> Result:
    """1초 단위로 1시간. policy: now(11/8 지금 코드) | lease(고친 방식)"""
    rng = random.Random(seed)
    disp, midm, qwen, vla = (_draw(rng, x) for x in (p.display, p.midm, p.qwen, p.vla))
    rates = {k: _draw(rng, getattr(p, f"{k}_per_min")) / 60 for k in ("chat", "photo", "return")}
    res = Result()
    ollama_until = -1          # Mi:dm 이 GPU 에 머무는 마지막 초(keep_alive 5분)
    ollama_mb = 0.0
    qwen_loaded = False        # now: 첫 사진 뒤 계속 상주
    qwen_busy_until = -1
    vla_from, vla_until = 0, -1  # 로봇 VLA 가 그래픽카드에 있는 구간 [vla_from, vla_until]
    return_busy_until = -1     # 관제탑은 반환을 한 번에 하나만(사용 중이면 '잠시 후' 안내)
    lease_until = -1           # lease: 누군가 사용권을 쥔 마지막 초
    queue_wait = []            # lease: 사진 분석 대기(사용권 기다림)
    for t in range(p.minutes * 60):
        def used():
            u = disp
            u += ollama_mb if t <= ollama_until else 0
            u += qwen if (qwen_loaded or t <= qwen_busy_until) else 0
            u += vla if vla_from <= t <= vla_until else 0
            return u

        def free():
            return TOTAL - MARGIN - used()

        # 챗봇 질문
        if rng.random() < rates["chat"]:
            res.events["chat"] += 1
            if policy == "lease" and t <= lease_until:
                res.cpu_chat += 1                       # 사용권 쥔 동안은 CPU 로(그래픽카드 안 씀)
            else:
                if t > ollama_until:                    # 새로 올림
                    can = max(0.0, free())
                    ollama_mb = min(midm, can)
                    if can < midm:
                        res.slow_chat += 1
                ollama_until = t + 300
        # 키오스크 사진
        if rng.random() < rates["photo"]:
            res.events["photo"] += 1
            if policy == "now":
                if not qwen_loaded and free() < qwen:
                    res.oom_qwen += 1
                else:
                    qwen_loaded = True
                    qwen_busy_until = t + rng.randint(6, 14)
            else:
                queue_wait.append(t)
        # 반환(로봇)
        new_return = rng.random() < rates["return"]
        if new_return:
            res.events["return"] += 1
            if t <= return_busy_until:
                res.busy += 1
                new_return = False
        if new_return:
            if rng.random() < p.uncertain and not (policy == "lease" and t <= lease_until):
                if t > ollama_until:
                    can = max(0.0, free())
                    ollama_mb = min(midm, can)
                    if can < midm:
                        res.slow_chat += 1
                ollama_until = t + 300
            dur = rng.randint(20, 60)
            if policy == "now":
                if free() < vla:
                    res.oom_vla += 1
                else:
                    vla_from, vla_until = t, t + dur
                return_busy_until = t + dur
            else:
                start = max(t, lease_until + 1)
                if start - t > 60:
                    res.gpu_wait_fail += 1
                else:
                    ollama_until = min(ollama_until, start - 1)   # 사용권 받으면 Ollama 내림
                    if TOTAL - MARGIN - disp < vla:
                        res.oom_vla += 1
                    vla_from, vla_until = start, start + dur
                    lease_until = vla_until
                return_busy_until = start + dur
        # lease: 사진은 사용권이 빌 때 하나씩(받고 → Ollama 내림 → 분석 → Qwen 내림 → 돌려줌)
        if policy == "lease" and queue_wait and t > lease_until:
            queue_wait.pop(0)
            ollama_until = min(ollama_until, t - 1)
            if TOTAL - MARGIN - disp < qwen:
                res.oom_qwen += 1
            dur = rng.randint(10, 20)                    # 모델 올리기 4~6초 + 분석 6~14초
            qwen_busy_until = t + dur
            lease_until = qwen_busy_until
        res.peak = max(res.peak, int(used()))
    return res


def summarize(policy: str, p: Premise, runs: int, seed: int = 0) -> dict:
    out = {"policy": policy, "runs": runs, "sessions_with_oom": 0, "oom_qwen": 0, "oom_vla": 0,
           "slow_chat": 0, "cpu_chat": 0, "gpu_wait_fail": 0, "peak_max": 0, "chat": 0, "photo": 0, "return": 0}
    peaks = []
    for i in range(runs):
        r = simulate(policy, p, seed + i)
        if r.oom_qwen or r.oom_vla:
            out["sessions_with_oom"] += 1
        for k in ("oom_qwen", "oom_vla", "slow_chat", "cpu_chat", "gpu_wait_fail"):
            out[k] += getattr(r, k)
        for k, v in r.events.items():
            out[k] += v
        peaks.append(r.peak)
    peaks.sort()
    out["peak_max"] = peaks[-1]
    out["peak_p95"] = peaks[int(len(peaks) * 0.95) - 1]
    out["oom_session_rate"] = round(out["sessions_with_oom"] / runs, 3)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="교육원 PC 6GB 그래픽카드 메모리 가상 시뮬레이션")
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--display", type=float, help="화면 사용량 MiB 고정(예: 1300 = 나쁜 쪽)")
    ap.add_argument("--vla", type=float, help="SmolVLA MiB 고정(예: 3000 = 나쁜 쪽)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    p = Premise()
    if a.display:
        p.display = (a.display, a.display)
    if a.vla:
        p.vla = (a.vla, a.vla)
    rows = [summarize(pol, p, a.runs) for pol in ("now", "lease")]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    print(f"전제: 그래픽카드 {TOTAL}MiB(여유 {MARGIN} 남김) · 화면 {p.display} · Mi:dm {p.midm} · Qwen {p.qwen} · VLA {p.vla}(추정)")
    for r in rows:
        print(f"[{r['policy']}] 시연 {r['runs']}회 중 메모리 넘침 {r['sessions_with_oom']}회({r['oom_session_rate']:.1%}) · "
              f"사진 분석 실패 {r['oom_qwen']} · 로봇 실패 {r['oom_vla']} · 챗봇 느림 {r['slow_chat']} · "
              f"사용권 중 CPU 답 {r['cpu_chat']} · 사용권 대기 실패 {r['gpu_wait_fail']} · 최고 사용 {r['peak_max']}MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
