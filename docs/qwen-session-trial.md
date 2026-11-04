# LF-11 Qwen 상주 세션 시험

2026-11-04. 사용자 PC에서 cold 함수 전체 19.65초, 모델 로딩 5.54초, 입력 처리·생성·검증 8.98초를 보고받았다. 모델·스키마·프롬프트·512 이미지 설정을 유지하며 요청 간 로딩 비용부터 분리한다. 이 도구는 사진 직접 분석용이며 YOLO 시퀀스 subprocess 연결을 교체한 운영 서버가 아니다.

tools/qwen_session.py는 검토한 비전 소스의 load_model을 한 번 호출하고 같은 프로세스·동일 Settings로 반복 요청한다. upstream lru_cache는 Settings 전체가 키이므로 log_dir 등 설정을 바꿔 캐시를 무효화하지 않는다. 입력 사진·결과를 캐시해 속도를 가장하지 않으며 같은 사진도 매번 실제 추론한다. 원래 모델 로더·특징 추출 코드를 수정하지 않는다.

## VS Code PowerShell

팀 저장소 pil2ya 체크아웃을 먼저 갱신하고 아래 명령을 사용한다. 두 경로는 사용자의 기존 설치 구조를 기준으로 했다.

```powershell
cd C:\00lsp\T_prj_edge\ai-lostfound-tower
git pull --ff-only origin pil2ya
& C:\00lsp\T_prj_edge\ai-lostfound-vision-trial\.venv-qwen\Scripts\python.exe .\tools\qwen_session.py --source-root C:\00lsp\T_prj_edge\ai-lostfound-vision-trial
```

READY 후 Photo>에 사진 전체 경로를 넣는다. 이후 같은 경로를 반복 입력하면 모델을 다시 로딩하지 않고 실제 재분석한다. 종료는 exit. 첫 이미지 추론과 이후 요청 시간을 나눠 보고하고, 최소 3회로 초기 경향을 확인한 후 고정 세트 반복 표본을 늘린다. 캐시 metadata의 model_load_seconds가 매 기록에 나타나도 새 로딩 시간이 아니며 요청 시간에 합산하지 않는다.

모델이 대기 중에도 VRAM을 점유하므로 다른 VLM·로봇 정책과 동시 상주시키지 않는다. 추론 오류 시 자동 재시작하지 않고 종료한다. 이 클라우드에서는 Windows/CUDA 상주·속도를 실측하지 않았고 GPU 없는 기존 저장소 시험과 Python 구문 확인만 가능하다.

## 생성 구간의 다음 개선 실험

- processor·GPU 전송·generate·decode·검증을 먼저 별도 계측한다. 기존 8.98초를 전부 GPU 연산 시간이라 단정하지 않는다. CUDA 동기화 경계를 사용하고 입력/출력 토큰 수를 기록한다.
- 현재 generate는 deterministic이며 inference_mode·SDPA·NF4가 이미 적용됐다. 같은 옵션을 새 최적화라고 중복 제안하지 않는다.
- 같은 8키 출력 계약과 관측 근거 규칙을 유지한 짧은 프롬프트, 짧은 값·배열을 비교한다. max_new_tokens는 상한이므로 EOS 전에 도달하지 않으면 낮춰도 빨라지지 않고, 너무 낮으면 JSON이 잘려 재시도할 수 있다.
- 512 대비 384 등 실제 시각 토큰 감소를 비교하되 문자·작은 표시 정확도를 함께 평가한다. 현재 코드의 파일 전처리 0.06초 최적화보다 generate 구간을 우선 조사한다.
- 재시도 기본 1회는 추가 추론 가능 횟수이며 사용자 첫 결과는 attempts=1이었다. 검증을 없애는 대신 형식 실패율을 측정하고 원인을 줄인다.
- 더 적은 특징을 먼저 내고 상세 특징은 뒤에서 처리하는 단계화는 지연을 숨길 수 있으나 소비자 요구·확인 질문에 필요한 특징을 검토해야 한다. 출력 계약을 임의 변경하지 않는다.

우선 상주 전후를 실측한 뒤 한 번에 설정 하나만 바꾼다. 전후 특징 정확도·JSON 성공률·실제 시간·VRAM을 확인하기 전 속도 향상 수치나 운영 적용 완료를 선언하지 않는다.
