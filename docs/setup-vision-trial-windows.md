# LF-11 사진 기반 YOLO·Qwen 테스트 준비 — Windows

검토일 2026-11-04. 기존 SO ARM Studio·WSL·Docker·Python 환경을 수정하지 않고 별도 폴더·가상환경에서 테스트한다. VS Code는 코드 편집기이며 모델이나 가상환경을 자동 제공하지 않는다. 로봇·카메라 없이 저장 사진으로 시작한다. 실제 로봇 명령은 실행하지 않는다.

## 제공 범위와 전제

팀원 브랜치 LF-3-yolo-aruco의 검토 커밋 `51600043c02a181178ee052644ccad1514559e4d`를 사용한다. 해당 버전에는 vision/과 qwen/ 소스가 모두 있다. 모델 가중치·사진·가상환경은 Git에 없고 별도로 준비한다. Git·Python 3.11 launcher(`py -3.11`)·GPU 호환 NVIDIA 드라이버와 저장소 읽기 권한이 필요하다. RTX 3050 6GB 환경에서의 실제 설치·모델 로딩은 이 클라우드에서 검증하지 않았다.

venv를 별도로 만든다. 영상 모델 추론 시 다른 GPU 모델·학습은 종료한다. qwen 요구 파일은 torch 2.9.1+cu128·Transformers 4.57.6·bitsandbytes 0.49.1 등을 지정한다. 설치 실패 시 기존 Studio 환경 패키지를 바꾸지 말고 실패 지점을 확인한다. 두 venv·모델 다운로드에 충분한 디스크 공간과 네트워크가 필요하며 GPU 메모리 적합성은 실제 로딩으로 확인한다.

## 1. 설치 스크립트 실행

진행 기록을 관리하는 pil2ya 체크아웃의 tools/setup_vision_trial.ps1을 사용한다. PowerShell에서 그 체크아웃 폴더로 이동한 후:

```powershell
& .\tools\setup_vision_trial.ps1 -LoadModel
```

대상 폴더 기본값은 `C:\00lsp\T_prj_edge\ai-lostfound-vision-trial`이다. 이미 존재하면 덮어쓰지 않고 중단한다. 다른 새 폴더를 쓰려면 `-Destination "C:\다른경로\vision-trial"`을 지정한다. PowerShell 정책이 스크립트를 차단하면 보안 설정을 임의 완화하지 말고 조직/PC 정책에 맞게 실행하거나 스크립트의 명령을 검토해 개별 실행한다.

스크립트는 팀원 브랜치를 별도 clone한 뒤 검토 커밋의 detached HEAD로 고정한다. 이는 **실행 확인 전용**이며 여기서 커밋·푸시하지 않는다. 프로젝트 수정·커밋은 기존 pil2ya에서 계속한다. 설치/점검 실패 시 nonzero 종료를 감지하고 멈추며, 실패한 새 폴더는 자동 삭제하지 않는다.

`-LoadModel`은 Qwen 모델을 최초 다운로드하고 GPU 로딩까지 점검한다. 생략하면 환경 점검만 수행하며 다음 단계의 모델 다운로드를 따로 해야 한다:

```powershell
cd C:\00lsp\T_prj_edge\ai-lostfound-vision-trial\qwen
..\.venv-qwen\Scripts\python.exe -m scripts.check_environment --load-model
```

## 2. VS Code에서 열기

File → Open Folder로 `ai-lostfound-vision-trial`을 연다. Python interpreter는 검출 작업에 `.venv-vision\Scripts\python.exe`를 선택한다. 아래 명령은 Python 경로를 명시하므로 터미널 활성화 여부에 의존하지 않는다. Qwen subprocess는 별도 .venv-qwen을 사용한다.

## 3. 사진 한 장으로 검출만 실행

로컬 물품 사진을 준비하고 저장소 루트에서 경로를 바꿔 실행한다. 사진은 Git에 올리지 않는다.

```powershell
cd C:\00lsp\T_prj_edge\ai-lostfound-vision-trial
.\.venv-vision\Scripts\python.exe -m vision.scripts.test_vision --image "C:\photos\test.jpg" --device cpu
```

첫 실행은 공식 YOLO26n 가중치를 다운로드할 수 있다. `outputs/vision/<실행ID>/debug.jpg`의 박스와 crops/를 확인한다. USB·립밤이 검출되지 않을 수 있으며 검출 0개면 다음 단계에서도 Qwen을 호출하지 않는다. 커스텀 item 모델 학습은 이 설치 과정에 포함하지 않는다.

## 4. Qwen까지 실행

```powershell
.\.venv-vision\Scripts\python.exe -m vision.scripts.run_sequence `
  --image "C:\photos\test.jpg" `
  --qwen-python ".\.venv-qwen\Scripts\python.exe" `
  --device cpu
```

YOLO는 CPU, Qwen은 CUDA GPU를 사용한다. 모델은 1단계에서 미리 캐시해야 하며 시퀀스는 오프라인 캐시를 사용한다. 출력 result_with_qwen.json에서 물품별 qwen.status와 features, sequence.status를 확인한다. complete는 실행·JSON 검증 완료이며 시각 정답을 의미하지 않는다. 처음 사진 2개 분석이 수십 초 걸릴 수 있다는 팀원 보고가 있으며 속도 보장은 없다. Ctrl+C 취소 시 부분 결과를 보존하는 구현이다.

ArUco 실측 설정이 없으므로 center_world_mm=null은 예상된 상태다. 임의 좌표를 채우거나 이 결과로 로봇을 움직이지 않는다. 아직 실제 SO-ARM 제어와 연결돼 있지 않다.

## 검증 상태와 다음 확인

이 문서·스크립트는 소스 검토에 기반한 준비본이다. 클라우드에서 Windows PowerShell 실행·CUDA 설치·모델 추론을 검증하지 않았다. 사용자 PC에서 설치/점검 → 사진 검출 → Qwen 분석 순서로 통과 여부를 확인한 뒤 준비 완료로 기록한다. 오류 공유 시 비밀값·개인정보·원본 사진이 로그에 포함되지 않게 주의한다. 모델·캐시·결과·venv는 커밋하지 않는다.
