# GPU 사용권 — STT·Qwen·VLA 순서 지키기 (11/4)

> 한줄 설명: 시연 PC 의 GPU(RTX 3050 6GB)는 **열쇠가 하나뿐인 방**이다. GPU 를 쓰려는 프로그램은 열쇠를 받아 들어가고, 모델을 내린 뒤 열쇠를 돌려준다.
> 코드: `agents/gpu_lease.py` (표준 라이브러리만 사용 → STT·Qwen·VLA 어느 가상환경에서나 import 가능). 순서안: 김건태 11/4

## 1. 왜 필요한가
- STT·Qwen3-VL-2B·SmolVLA 는 **따로 실행되는 프로그램**이라 서로 GPU 를 쓰는지 모른다
- 분실인 웹의 음성 입력(STT)은 **반환 도중에도 다른 사람이** 할 수 있다 → 같은 6GB 에 두 모델이 올라가면 메모리 부족·느려짐·실패
- 모델을 "껐다"고 해도 메모리가 남아 있을 수 있다 → 열쇠를 넘기기 전에 메모리 확인(선택)

```
STT 입력 확정 → STT 해제 → 탑뷰 촬영·Qwen 분석 → Qwen 해제 → CPU 전처리·매칭 → 사전 접근·VLA 집기
   [stt 열쇠]                  [qwen 열쇠]                    (열쇠 없음)         [vla 열쇠 — 관제탑이 받음]
```

## 2. 모듈에 넣는 법 (각 담당, 몇 줄)
```python
from agents.gpu_lease import gpu_lease, GpuBusy

try:
    with gpu_lease("qwen", wait=120):           # 이름: stt | qwen | vla | reviewer, wait = 최대 대기 초
        model = load_model()
        result = run(model)
        del model
        torch.cuda.empty_cache()                # 열쇠를 돌려주기 전에 GPU 메모리를 비운다(중요)
except GpuBusy as e:
    print(e)    # "GPU 사용 중(vla, 35초째) — 120초 기다렸지만 받지 못함" → 화면에 "잠시 후 다시" 안내
```
- 저장소 밖 폴더에서 실행하는 모듈은 `sys.path` 에 저장소 폴더를 넣거나 `agents/gpu_lease.py` 한 파일을 복사해 써도 된다(같은 잠금 파일만 보면 됨)
- 잠금 파일: 기본 임시 폴더 `agentops_gpu.lock`. 바꾸려면 모든 프로그램의 환경값 `GPU_LEASE_FILE` 을 같은 값으로

| 모듈 | 열쇠 이름 | 담당 | 못 받으면 |
| --- | --- | --- | --- |
| STT(분실인 음성 입력) | `stt` | 김건태·김재민(웹) | 화면 "잠시 후 다시 말씀해 주세요" 또는 글자 입력 |
| 탑뷰·등록기계 Qwen 분석 | `qwen` | 김건태 LF-3 | 결과 파일 없음 → 관제탑은 직원 확인 |
| VLA 집기 | `vla` | **관제탑이 받음**(사전 접근 전) | 로봇 안 움직임 → 직원 확인 |
| LLM 검토(Ollama) | (필요 없음) | 변재원 — 시연은 **CPU 실행**(`MAIN_AI_DEVICE=cpu`, 11/4)이라 GPU 를 쓰지 않음. GPU 로 돌릴 때만 `reviewer` | 검토 보류 → 직원 확인 |

## 3. 관제탑 동작
- 반환 흐름의 **사전 접근 직전**에 `vla` 열쇠를 받는다(`TOWER_GPU_WAIT` 초, 기본 60). 받으면 단계에 "GPU 사용권 받음"
- 못 받으면 상태를 `반환 중` 으로 바꾸지 않고 **직원 확인** + 경보: `GPU 사용권 없음 — 로봇을 움직이지 않음: GPU 사용 중(qwen, 40초째)…`
- 반환이 끝나거나 멈추면(정지·오류 포함) 열쇠를 돌려준다
- `/health` 의 `gpu.holder` 로 지금 누가 GPU 를 쓰는지 본다
- 프로그램이 죽으면 운영체제가 잠금을 풀어 준다 → 남은 열쇠 때문에 영원히 막히지 않음(시험으로 확인)

| 환경값(.env) | 기본 | 뜻 |
| --- | --- | --- |
| `TOWER_GPU_LEASE` | 켬 | `0` 이면 관제탑이 열쇠를 받지 않음 |
| `TOWER_GPU_WAIT` | 60 | 열쇠를 기다리는 최대 초 |
| `TOWER_GPU_FREE_MB` | 없음 | 열쇠를 받은 뒤 남은 메모리가 이 값 이상일 때만 진행(VLA 실측 뒤 TBD) |
| `GPU_LEASE_FILE` | 임시 폴더 | 잠금 파일 위치(모든 프로그램 같은 값) |

## 4. 아직 정할 것
- 각 모듈의 `wait` 값(STT 는 짧게, Qwen 은 분석 시간만큼) — 담당별 실측 후
- VLA 에 필요한 남은 메모리(`TOWER_GPU_FREE_MB`) — LF-19 실측 후
- STT 를 웹 서버가 돌린다면 웹 쪽에서 열쇠 받기(김재민 LF-5·6 과 협의)

## 5. 11/8 6GB 그래픽카드 안전 — 시뮬레이션과 고친 점 (변재원)
한줄 설명: 챗봇·메인 AI(Mi:dm, Ollama)와 키오스크 사진 Qwen 이 그래픽카드에 계속 머물러 있으면, 로봇 VLA 를 올릴 자리가 없어 로봇이 멈춘다.
그래서 **GPU 사용권을 쥔 동안에는 한 프로그램만 그래픽카드를 쓰고, 나머지는 내리거나 CPU 로 돌린다.**

### 5-1. 전제(숫자 출처)
| 항목 | 값(MiB) | 출처 |
|---|---|---|
| 그래픽카드 | 6144, 여유 300 남김 | RTX 3050 6GB · 여유는 Windows·조각화 몫(추정) |
| 화면(모니터가 3050 에 꽂힘) | 700~1300 | docs/ollama/README.md "약 1GB", 집 PC 1216 실측 |
| Mi:dm 2.0 Mini(Ollama, num_ctx 4096) | 2100~2400 | 11/8 집 PC 실측(두 모델 합 4844) − Qwen 몫 |
| Qwen3-VL-2B NF4 작업자 | 2300~2700 | 11/8 집 PC peak reserved 2298 + CUDA 기본(추정) |
| SmolVLA 집기 | 1500~3000 | **추정·TBD**(LF-19 실측 전) |
| 사건 빈도(분당) | 질문 0.5~3 · 사진 0.1~0.5 · 반환 0.05~0.3 · 애매한 매칭 30% | 시연 상황 추정 |
- Ollama 는 자리가 모자라면 일부를 CPU 로 돌려 느려질 뿐 죽지 않는다. PyTorch(Qwen·VLA)는 모자라면 OOM 으로 실패

### 5-2. 결과(`python tools/gpu_budget_sim.py --runs 2000`, 1시간 시연 2000번)
| 전제 | 지금 방식(11/8 오전 코드) | 고친 방식 |
|---|---|---|
| 범위 무작위 | 시연 99% 에서 넘침(사진 분석 실패·로봇 실패) | 넘침 0 · 최고 4272MiB |
| 나쁜 쪽(화면 1300 · VLA 3000) | 99.9% 넘침 | 넘침 0 · 최고 4300MiB |
- 지금 방식이 넘치는 이유: ① Qwen 작업자가 첫 사진 뒤 계속 상주(약 2.5GB) ② Mi:dm 이 마지막 질문 뒤 5분 상주(약 2.2GB) ③ 그 위에 로봇 VLA → 화면까지 더하면 6GB 초과
- 고친 방식의 대가: 사용권을 쥔 동안(사진 10~20초, 로봇 20~60초) 들어온 챗봇 질문은 CPU 로 답함(시뮬레이션상 질문의 약 18%) → CPU 답 시간은 `python tools/ollama_cpu_bench.py` 로 교육원 PC 실측(TBD)

### 5-3. 고친 점(코드)
| 어디 | 바뀐 점 | 끄기 |
|---|---|---|
| `agents/local_model.py` | 누가 GPU 사용권을 쥐었으면 Ollama 요청을 CPU 로(`num_gpu=0`) — 챗봇·메인 AI·분석 에이전트 모두 이 함수를 거침. `unload_local_models()` 로 Ollama 모델 내리기 | `OLLAMA_GPU_GUARD=0` |
| `agents/service.py` (반환) | 로봇 `vla` 사용권을 받으면 Ollama 모델을 내림 | `TOWER_OLLAMA_UNLOAD=0` |
| `tools/intake_qwen_worker.py` | 사진 한 장마다 `qwen` 사용권 → Ollama 내림 → 분석 → Qwen 내림 → 돌려줌. 로봇이 GPU 를 쓰면 실패로 세지 않고 기다림. 관제탑이 늦게 켜져도 5초마다 다시 연결 | `QWEN_KEEP_MODEL=1`(8GB 이상 PC) |

### 5-4. 교육원 PC 에서 확인할 것(TBD)
1. `python tools/ollama_cpu_bench.py` — CPU 답 시간(40초 넘으면 챗봇은 문서 문장으로 대신 답함)
2. 시연 흐름 중 `nvidia-smi` — 사진 분석 중·로봇 동작 중 최고 사용량이 5.8GB 아래인지
3. SmolVLA 실측값이 나오면 `tools/gpu_budget_sim.py` 의 `vla` 범위를 바꿔 다시 돌린다
