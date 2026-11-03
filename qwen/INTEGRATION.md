# 저장소에 포함된 Qwen 소스

이 폴더는 기존 외부 qwen 프로젝트의 Python 소스·테스트·의존성 파일을 복사한 것입니다. 원본 외부 프로젝트는 변경하지 않았습니다. `config/settings.py`, `src/model_loader.py`, `src/image_preprocess.py`, `src/benchmark.py`는 복사 시점의 원본과 동일합니다. 성능 분석 시 이 네 파일과 `../vision/item_features.py`를 함께 확인하세요.

원래 지갑 특징 추출 코드와 스키마도 보존했습니다. 현재 일반 물품 시퀀스는 `vision/item_features.py`를 사용하고 이 폴더의 모델 로더·전처리·벤치마크를 재사용합니다. WALLET_MAX_NEW_TOKENS, WALLET_RETRIES 등 기존 환경변수 이름을 유지합니다. 다만 시퀀스 worker는 max_edge=512와 실행 폴더의 log_dir을 명시적으로 지정합니다.

## 다른 PC에서 설치

저장소 루트에서 Qwen 전용 환경을 새로 생성합니다. 가상환경 자체와 가중치·캐시는 Git에 포함하지 않습니다.

```powershell
py -3.11 -m venv .venv-qwen
.\.venv-qwen\Scripts\python.exe -m pip install -r qwen/requirements.txt
```

CUDA 드라이버와 wheel 호환성은 해당 PC에서 확인해야 합니다. 모델 최초 다운로드·검증:

```powershell
cd qwen
..\.venv-qwen\Scripts\python.exe -m scripts.check_environment --load-model
cd ..
```

이 단계는 수 GB 가중치를 로컬 `qwen/.cache/huggingface`에 다운로드할 수 있습니다. 이후 시퀀스는 오프라인으로 캐시를 사용합니다.

```powershell
.\.venv-vision\Scripts\python.exe -m vision.scripts.run_sequence `
  --image "C:\photos\topview.jpg" `
  --qwen-python ".\.venv-qwen\Scripts\python.exe"
```

기본 소스 경로는 저장소의 qwen/입니다. `--qwen-root`는 외부 소스를 명시적으로 선택할 때만 필요합니다. 다른 위치의 모델 캐시는 `--qwen-cache-dir`로 지정합니다. 정상 가상환경에는 `--qwen-site-packages`가 필요 없습니다.

## 현재 원 개발 PC에서 재사용

기존 환경과 캐시를 복사하거나 수정하지 않고 아래 명령으로 저장소 소스를 실행할 수 있습니다. 기존 가상환경 launcher의 이전 경로 문제 때문에 Python과 패키지 경로를 따로 지정합니다.

```powershell
& ..\.venv-vision\Scripts\python.exe -m vision.scripts.run_sequence `
  --image "C:\Users\user\Pictures\Camera Roll\topview.jpg" `
  --qwen-python "..\qwen\.python\cpython-3.11.18-windows-x86_64-none\python.exe" `
  --qwen-site-packages "..\qwen\.venv\Lib\site-packages" `
  --qwen-cache-dir "..\qwen\.cache\huggingface"
```

사진·실행 결과·로그·캐시·가중치·가상환경은 제외하고 소스와 의존성 파일만 공유합니다.
