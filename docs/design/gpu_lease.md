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
| LLM 검토(Ollama) | `reviewer` | 변재원(시연에서는 끔) | 검토 보류 → 직원 확인 |

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
