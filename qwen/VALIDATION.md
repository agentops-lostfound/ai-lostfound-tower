# 실행 검증 보고서

검증일: 2026-11-02 (Asia/Seoul). 프로젝트: `C:\Users\user\qwen`.

전용 환경, CUDA 실제 연산, Qwen 모델 로딩, NF4 4-bit 확인, 오프라인 합성 이미지 GPU 추론, JSON 검증·저장 및 단위 테스트가 성공했습니다. **실제 지갑 사진이 제공되지 않아 실제 지갑 특징 정확성과 실제 지갑 사진의 성능은 미검증입니다. 전체 완료 조건을 모두 충족한 상태는 아닙니다.**

## 1. 생성 파일

- 설정: `.gitignore`, `.env.example`, `.vscode/settings.json`, `requirements.txt`, `requirements.lock.txt`, `config/__init__.py`, `config/settings.py`
- 모듈: `src/__init__.py`, `src/device_check.py`, `src/model_loader.py`, `src/image_preprocess.py`, `src/feature_extractor.py`, `src/schemas.py`, `src/json_validator.py`, `src/benchmark.py`
- CLI: `scripts/__init__.py`, `scripts/check_environment.py`, `scripts/analyze_wallet.py`, `scripts/analyze_batch.py`, `scripts/gpu_smoke.py`
- 테스트: `tests/test_schema.py`, `tests/test_json_validator.py`, `tests/test_image_preprocess.py`, `tests/test_extraction.py`, `tests/test_workflow.py`
- 문서: `README.md`, `VALIDATION.md`
- 로컬 전용: `.python/`, `.tools/`, `.venv/`, `.cache/`, `data/input/`, `data/output/`, `logs/`

기존 프로젝트 파일 삭제나 시스템 Python 패키지 변경은 하지 않았습니다. 현재 루트를 프로젝트 폴더로 사용했습니다.

## 2. 설치 버전

| 항목 | 버전 |
|---|---|
| Python | 3.11.18, 프로젝트 내부 독립 설치 |
| PyTorch / torchvision | 2.9.1+cu128 / 0.24.1+cu128 |
| Transformers | 4.57.6 |
| Accelerate / bitsandbytes | 1.12.0 / 0.49.1 |
| Pillow / Pydantic | 12.1.0 / 2.12.5 |
| pytest / hf-xet | 9.0.2 / 1.8.0 |

TorchAudio 미설치. 전체 패키지 버전은 `requirements.lock.txt`에 기록했습니다.

## 3. GPU 및 CUDA

NVIDIA GeForce RTX 3050 6GB, 드라이버 610.88. 드라이버 CUDA 지원 표시 13.3, 실제 PyTorch CUDA 런타임 12.8. CUDA 텐서 연산이 성공했습니다. CPU는 Intel64 Family 6 Model 198 Stepping 2, 20 logical CPUs. 총 RAM 약 15.42GiB, 진단 당시 여유 약 1.6~2.6GiB. 장치 진단은 `logs/environment.json`에 저장했습니다.

## 4–5. 모델 로딩 및 실제 양자화

- 모델: `Qwen/Qwen3-VL-2B-Instruct`
- 스냅샷: `89644892e4d85e24eaac8bacfd4f463576704203`
- SDPA, float16 연산, 전체 모델 parameter의 CUDA 배치 확인
- `is_loaded_in_4bit=True`, 실제 `bitsandbytes.nn.Linear4bit` 300개 확인
- 모든 양자화 레이어의 quant_state 및 `nf4` 확인
- CPU fallback이나 혼합 배치 없음
- Xet 다운로드 재시도 완료 구간 약 427.18초 (그 이전 HTTP 시도 시간 제외)
- 최초 성공 순수 모델 로딩 약 6.85초; 후속 오프라인 실행 약 5.48초

로딩 증거: `logs/benchmark-3b4884acb9b2471c9989c61f321c06a6.json` 및 CSV.

## 6–7. 테스트 이미지와 생성 JSON

입력은 `PIL.Image.new('RGB', (384, 256), 'white')`로 만든 **합성 흰색 이미지**이며 실제 지갑 사진이 아닙니다. 오프라인 모드에서 로컬 캐시만 사용했습니다. 실제 모델 응답을 검증한 결과입니다.

```json
{
  "category": "other",
  "colors": [],
  "shape": null,
  "wallet_type": null,
  "materials": [],
  "logos_or_text": [],
  "sticker_status": "absent",
  "stickers": [],
  "distinctive_features": []
}
```

결과: `data/output/synthetic-blank.json`. 최종 실행에서 1회 생성으로 JSON 검증을 통과했습니다.

## 8–9. 시간과 최대 VRAM

- 전처리: 약 0.00020초
- 추론 구간: 약 6.50872초 (processor·생성·디코드·검증 포함)
- 전체 함수: 약 16.881초 (모델 초기화·로딩 포함)
- 최대 할당 VRAM: 1,795,255,808 bytes ≈ 1.67GiB
- 최대 예약 VRAM: 2,178,940,928 bytes ≈ 2.03GiB
- 로딩 중 최대 할당 VRAM: 2,064,226,816 bytes ≈ 1.92GiB

추론 증거: `logs/benchmark-9ea1299773d04553a6199d631a0e9891.json` 및 CSV. VRAM은 PyTorch allocator 기준이며 다른 앱·드라이버 메모리를 포함하지 않습니다. 합성 이미지 한 번의 결과를 실제 사진 평균 성능으로 일반화할 수 없습니다.

## 10. 테스트와 발생 오류

최종 `python -m pytest -q`: **22 passed** (1.68초). `pip check`: **No broken requirements found**.

이미지 테스트는 JPEG/PNG·EXIF·RGB·PIL·비확대·손상/경로 오류를 확인했습니다. JSON 테스트는 필수 필드·null·복수 색상·추가 키·잘못된 타입·중복 키·잘못된 JSON을 확인했습니다. 모의 추론 테스트는 재시도 제한·실패 원문 보존·재시도 후 성공·일괄 처리에서 개별 실패 이후 계속 및 파일명 충돌 방지를 확인했습니다. 실제 장치 검사는 CUDA 연산·모델/Processor import·GPU 로딩·합성 이미지 GPU 추론을 확인했습니다.

초기 Python은 3.15만 존재하고 `python` PATH 명령도 없었습니다. 프로젝트 내부 독립 Python 3.11과 `.venv`로 해결했습니다. 기존 uv 실행 별칭이 작동하지 않아 `.tools`에 도구를 따로 설치했습니다.

샌드박스 네트워크 제한은 승인된 설치 명령으로 해결했습니다. 느린 HTTP 다운로드는 해당 다운로드 프로세스만 중지하고 hf-xet으로 재시도해 완료했습니다. 기존 다운로드 파일은 삭제하지 않았습니다. Windows 심볼릭 링크 제한은 파일 복사 캐시로 처리됐고 관리자 모드나 Developer Mode는 활성화하지 않았습니다.

첫 GPU 추론에서 모델이 허용되지 않은 `wallet_features` 필드를 추가했습니다. 재시도 후에도 검증 실패를 올바르게 보고했고 원문을 `logs/invalid-*.json`에 보존했습니다. 정확한 9개 필드만 출력하도록 프롬프트를 강화한 후 재실행해 통과했습니다. 잘못된 응답에서 필드를 자동으로 삭제하는 보정은 하지 않았습니다. 모델 기본 샘플링 설정의 무시 경고도 생성 인자에서 제거했습니다.

## 11. 아직 검증하지 않은 부분

실제 사용자 지갑 사진의 특징 정확성·성능 및 실제 여러 지갑 사진의 배치 전체 실행은 미검증입니다. 배치 제어 흐름은 자동 테스트로 확인했고 모델 재사용은 캐시 로더로 구현했습니다. 사진에 따라 JSON 실패 또는 시각적 오인식이 가능하며 스키마 통과는 시각적 정확성을 보증하지 않습니다.

## 12. 다음 실행 명령

실제 지갑 사진을 `data/input/wallet.jpg`에 넣고 프로젝트 루트 PowerShell에서 실행합니다.

```powershell
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe -m scripts.analyze_wallet --image "data/input/wallet.jpg"
# 여러 실제 사진을 넣은 뒤:
.\.venv\Scripts\python.exe -m scripts.analyze_batch --input "data/input"
```

단일 결과는 `data/output/wallet.jpg.json`, 성능·상태는 `logs/benchmark-*`에 저장됩니다.
