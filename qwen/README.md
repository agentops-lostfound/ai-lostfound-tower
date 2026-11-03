# 지갑 특징 추출 — Qwen3-VL 로컬 GPU

Windows에서 `Qwen/Qwen3-VL-2B-Instruct` 전체 사전학습 모델을 bitsandbytes NF4 4-bit로 로드하여 분실물 검색용 시각 특징을 추출합니다. 클라우드 추론 API, 파인튜닝, YOLO는 사용하지 않습니다. 현재 폴더가 프로젝트 루트입니다.

## 환경 및 설치

권장: Windows x64, Python 3.11, RTX 3050 6GB 이상, 최신 호환 NVIDIA 드라이버, 모델·패키지·캐시에 충분한 디스크 공간(약 15GB 이상 권장). CUDA Toolkit을 별도 설치하지 않아도 PyTorch CUDA wheel의 런타임을 사용합니다. 드라이버가 표시하는 CUDA 상한과 `torch.version.cuda`는 다를 수 있습니다.

이 PC에는 프로젝트 내부 `.python`에 독립 Python 3.11을 설치하고 `.venv`를 생성했습니다. 다른 PC에서는 다음을 사용합니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scripts.check_environment
.\.venv\Scripts\python.exe -m pytest -q
```

주요 고정 버전은 `requirements.txt`, 전체 설치 버전은 `requirements.lock.txt`에 기록합니다. torch 2.9.1+cu128 / torchvision 0.24.1+cu128은 [공식 호환 조합](https://pytorch.org/get-started/previous-versions/#v2-9-1)입니다. TorchAudio는 설치하지 않습니다. VS Code는 `.vscode/settings.json`의 인터프리터를 선택하거나 Python: Select Interpreter에서 `.venv\Scripts\python.exe`를 지정합니다.

## 다운로드 및 실행

최초 명령은 수 GB의 모델 가중치를 `.cache/huggingface`에 다운로드합니다. 다운로드/캐시 확인 시간과 로딩 시간을 별도로 기록합니다. 이후 동일 캐시를 재사용합니다. [공식 모델 카드](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct), [bitsandbytes Windows 설치 안내](https://huggingface.co/docs/bitsandbytes/main/en/installation)를 참고했습니다.

```powershell
.\.venv\Scripts\python.exe -m scripts.check_environment --load-model
.\.venv\Scripts\python.exe -m scripts.analyze_wallet --image "data/input/wallet.jpg"
.\.venv\Scripts\python.exe -m scripts.analyze_batch --input "data/input"
```

단일 결과 기본 경로는 `data/output/wallet.jpg.json`입니다. `--output "data/output/custom.json"`으로 변경합니다. 일괄 처리는 입력 폴더 바로 아래 JPG/JPEG/PNG를 순차 처리하며 모델을 재사용하고 개별 실패 이후 계속합니다. 하나라도 실패하면 종료 코드 1을 반환합니다. 기존 동일 이름 결과는 성공 시 덮어씁니다. 실패 시 기존 결과가 최신 성공으로 보이지 않도록 실행 로그의 타임스탬프와 상태를 확인하세요.

완전 오프라인 실행(모델 캐시 준비 후):

```powershell
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe -m scripts.analyze_wallet --image "data/input/wallet.jpg"
```

설정은 `config/settings.py`와 환경변수로 지정합니다. `.env.example`은 예시이며 자동으로 읽지 않습니다.

```powershell
$env:WALLET_MAX_EDGE="512"
$env:WALLET_MAX_NEW_TOKENS="384"
$env:WALLET_RETRIES="1"
```

긴 변 768 기본값으로 비율 유지 축소하며 자체 전처리는 업스케일하지 않습니다. 모델 processor는 패치 정렬을 위해 크기를 조정할 수 있습니다. EXIF 방향 보정 후 RGB로 변환합니다. 아주 작은 이미지는 경고합니다. 이미지 크기는 원본과 전처리 결과를 기록합니다.

## 출력 계약

모든 필드가 필수이고 추가 필드·타입 강제 변환·중복 JSON 키를 허용하지 않습니다. JSON 코드펜스만 제거하며 잘못된 JSON을 임의 보정하거나 특징을 만들어 채우지 않습니다. 검증 실패 원문과 오류는 `logs/invalid-*.json`에 기록하고 기본 한 번 재추론합니다. 최종 실패 시 예외를 발생시킵니다.

아래는 **스키마 예시이며 실제 사진 추론 결과가 아닙니다**.

```json
{
  "category": "unknown",
  "colors": [],
  "shape": null,
  "wallet_type": null,
  "materials": [],
  "logos_or_text": [],
  "sticker_status": "unknown",
  "stickers": [],
  "distinctive_features": []
}
```

category: wallet/other/unknown, sticker_status: present/absent/unknown. present는 하나 이상의 `{ "shape": null, "position": null }` 스티커를 요구합니다. absent와 unknown은 빈 배열을 요구합니다. 그 밖의 관찰값은 자유 문자열입니다. 스키마 통과는 시각적 정확성을 보증하지 않습니다. 브랜드·재질은 모델이 잘못 추정할 수 있어 실제 이미지 대조 평가가 필요합니다.

## Python 함수 / 추후 통합

```python
from PIL import Image
from src.feature_extractor import extract_wallet_features

features = extract_wallet_features("data/input/wallet.jpg")
with Image.open("data/input/wallet.jpg") as image:
    wallet_crop = image.crop((10, 10, 200, 200))
    features = extract_wallet_features(wallet_crop)
```

동일 프로세스·설정에서 로더 캐시가 모델을 재사용합니다. 순차 호출용이며 동시 요청 서버는 별도 직렬화가 필요합니다. 이후 YOLO가 반환하는 PIL crop을 이 함수에 전달하고, DB에는 검증된 특징·원본 식별자·모델 버전·관찰 시간을 저장하여 Matching Engine의 색상/텍스트/특징 검색에 연결할 수 있습니다. 이번 단계에는 해당 서버를 구현하지 않습니다.

## 성능 및 문제 해결

`logs/environment.json`은 환경 진단, `logs/benchmark-*.json` 및 CSV는 모델 정보·로딩/전처리/추론 시간·GPU 최대 할당/예약 메모리·성공 여부를 기록합니다. 추론 시간에는 processor 처리, 생성, 디코드, 검증 및 재시도가 포함됩니다. CUDA 동기화 후 측정합니다. VRAM 수치는 PyTorch allocator 기준이며 다른 앱·드라이버 메모리는 포함하지 않습니다. `nvidia-smi`로 전체 사용량을 확인합니다.

- `torchvision::nms` 오류: torch/torchvision을 동일 CUDA 인덱스의 공식 조합으로 전용 가상환경에 설치합니다. 기존 시스템 패키지를 제거하지 마세요.
- TorchAudio CUDA 충돌: 이 환경은 TorchAudio를 설치하지 않습니다.
- Processor torchvision 오류: `requirements.txt`의 torchvision 설치 및 import를 확인합니다.
- CUDA 미인식: 드라이버, 실행 인터프리터, CUDA wheel인지 진단합니다. `check_environment`는 실제 CUDA 텐서 연산도 실행합니다.
- CUDA OOM: `nvidia-smi`에서 다른 앱 사용량을 확인하고 사용자가 불필요한 앱을 종료한 뒤 긴 변 512, 토큰 384 등으로 줄입니다. 토큰을 너무 줄이면 JSON이 잘릴 수 있습니다. 로딩 OOM에는 입력 크기 변경 효과가 제한적입니다.
- CPU 혼합 배치와 조용한 CPU fallback을 허용하지 않습니다. 로더가 모든 모델 parameter의 CUDA 배치, 4-bit 레이어 및 양자화 상태를 확인합니다.
- bitsandbytes backend 실패: [공식 지원 범위](https://huggingface.co/docs/bitsandbytes/main/en/installation)를 점검합니다. 해결되지 않으면 별도 GGUF/llama.cpp 양자화 또는 명시적인 CPU 실행 프로젝트를 검토할 수 있으나 이 구현에서 자동 전환하지 않습니다.

실제 사용자 지갑 사진을 `data/input`에 넣어 실행하기 전에는 실제 지갑 분석 성공으로 간주하지 않습니다. 검증 상태는 `VALIDATION.md`에 기록합니다. 가중치·캐시·가상환경·입력·결과·로그는 Git에서 제외합니다.
