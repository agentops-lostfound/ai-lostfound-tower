# SmolVLM2-500M 비교 실험

기존 Qwen 소스, 스키마, 가중치, 결과, `.venv` 설치 패키지를 수정하지 않는 추가 실험입니다. 새 코드는 `scripts/compare_smolvlm.py` 한 파일입니다.

## 별도 실행 환경

`.venv-smol`은 독립 가상환경이며 `qwen_shared.pth`를 통해 기존 `.venv/Lib/site-packages`를 읽어 사용합니다. 기존 환경에는 없던 `num2words==0.5.14`, `docopt==0.6.2`만 별도 환경에 설치했습니다. 기존 환경을 제거하거나 이동하면 공유 참조도 작동하지 않습니다. torch/transformers를 업그레이드하지 않았습니다.

공식 [모델 카드](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct)의 `AutoProcessor`와 `AutoModelForImageTextToText`를 사용합니다. 이 PC에서는 FP16, SDPA, CUDA 고정 배치를 사용하며 CPU fallback은 없습니다. 기존 Qwen은 기존 NF4 로더를 그대로 사용합니다.

## 실행

PowerShell, 프로젝트 루트:

```powershell
# 최초 한 번: SmolVLM만 별도 캐시에 다운로드
.\.venv-smol\Scripts\python.exe -m scripts.compare_smolvlm --download-only

# 같은 실제 사진 2장, 각 모델에서 각 사진 2회 (총 8회 생성)
.\.venv-smol\Scripts\python.exe -m scripts.compare_smolvlm --limit 2 --repeats 2

# 전체 사진을 각 모델에서 2회씩 반복
.\.venv-smol\Scripts\python.exe -m scripts.compare_smolvlm --limit 0 --repeats 2
```

비교 실행 자체는 두 모델 모두 오프라인 캐시만 사용합니다. 기본 `data/input` 바로 아래 JPG/JPEG/PNG를 이름순으로 선택합니다. `--input`, `--max-edge`(기본 768), `--max-new-tokens`(기본 512)를 지정할 수 있습니다. 재시도 없이 동일 조건의 단일 생성 결과를 평가합니다. 기존 CLI의 재시도 포함 시간과 직접 비교하면 안 됩니다.

## 결과

매번 새로운 `data/output/comparison-smolvlm/날짜-고유번호/`에만 결과를 저장합니다.

- `REPORT.md`: 모델별 로딩·이미지별 시간·토큰·VRAM·JSON 성공 여부, 특징 항목을 나란히 표시, 각 반복의 실제 JSON 또는 실패 원문
- `paired-results.json`: 동일 이미지의 기존 Qwen 결과, 새 Qwen 결과, Smol 결과를 함께 보존. `visual_accuracy=not_reviewed`
- `measurements.csv`: 수치 비교
- `images/`: 실제 입력 이미지 복사 및 manifest의 SHA-256
- `qwen/`, `smol/`: 로딩 기록, 각 생성의 raw 응답·검증 결과, tensor shape
- `protected-before.json`, `preservation.json`: 기존 소스·문서·설치 기록·Qwen 스냅샷·기존 최상위 결과 파일 해시와 변경 여부
- `*-console.txt`: 워커 출력 및 오류

모델별 독립 프로세스를 순차 실행하며 한 프로세스에서 한 번만 로딩합니다. 첫 이미지 첫 호출은 `first_call`, 이후 호출은 `subsequent`입니다. 같은 사진의 repeat 2는 모델과 CUDA allocator가 준비된 상태입니다. 양쪽 모두 동일 PIL 전처리와 기존 프롬프트·스키마를 재사용하지만, 모델 내부 resize/patch splitting은 다릅니다. tensor shape로 실제 처리 입력을 확인할 수 있습니다.

모델+Processor 로딩은 다운로드와 Python import를 제외한 시간입니다. 추론 구간은 Processor·전송·생성·디코드·검증을 포함하고, 순수 generate 구간도 따로 기록합니다. CUDA 동기화를 적용합니다. 토큰 수는 생성 EOS를 포함하며 모델마다 tokenizer가 달라 토큰 수만으로 효율을 판단할 수 없습니다. VRAM은 PyTorch 최대 할당/예약량으로 다른 앱의 사용량은 포함하지 않습니다.

JSON 실패도 실험 결과이며 원문을 보존합니다. 잘못된 JSON을 수정하거나 특징을 만들어 채우지 않습니다. JSON 검증 성공과 실제 이미지 특징 정확성은 별개입니다. `REPORT.md`의 원본 이미지 링크와 나란히 표시된 결과를 사람이 확인해야 합니다. 소수 사진·고정 모델 순서의 결과로 전체 데이터나 다른 장치 성능을 일반화하지 않습니다.

## 이번 실측 결과 (2026-11-02)

상세 보고서: [REPORT.md](../data/output/comparison-smolvlm/20261102-174231-4433b918/REPORT.md)

실제 지갑 사진 `01-3_jpg.rf...jpg`, `01-4_jpg.rf...jpg` 두 장을 각 모델에서 두 번씩 측정했습니다. Qwen은 4회 모두 스키마 검증에 통과했고, Smol은 특징값 대신 JSON 스키마를 되풀이해 4회 모두 검증에 실패했습니다. Smol도 FP16 CUDA 생성은 정상 수행했습니다. 이것은 이번 동일 프롬프트 조건의 결과이며 모델 전체의 특징 추출 능력을 단정하는 평가가 아닙니다.

| 모델 | 모델+Processor 로딩 | 이미지당 추론 범위 | 최대 추론 할당 VRAM | JSON 검증 |
|---|---:|---:|---:|---:|
| Qwen NF4 | 8.469초 | 16.058~17.231초 | 1.806GiB | 4/4 |
| SmolVLM2 FP16 | 3.557초 | 13.481~14.517초 | 1.556GiB | 0/4 |

Smol 가중치 파일의 실제 다운로드 크기는 약 2.03GB였습니다. 최초 Windows 링크 권한 오류는 누락된 작은 설정 파일만 재시도해 해결했습니다. 향후 신규 캐시 다운로드는 Windows 링크 지원 검사 경합을 줄이도록 파일을 순차 다운로드합니다.

기존 Qwen 파일 보존 검사는 `preservation.json`에서 `unchanged: true`, `changed: []`입니다. 실제 추출 특징의 시각적 정확성, 전체 42장 성능, 프롬프트 최적화 후 Smol 성능은 미검증입니다.
