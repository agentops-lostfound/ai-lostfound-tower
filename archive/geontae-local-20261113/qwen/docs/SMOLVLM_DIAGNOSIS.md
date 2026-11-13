# SmolVLM2-500M 지갑 특징 추출 진단 결과

2026-11-02, RTX 3050 6GB, FP16/SDPA, 기존 `.venv-smol`과 로컬 모델 캐시 사용. 이번 작업에서 패키지 설치·업그레이드, Qwen 소스·스키마·가중치 변경은 하지 않았습니다.

## 최종 판단: B

**간단한 프롬프트에서는 개선되지만, 일부 특징 인식에 한계가 있습니다.**

한 문장 설명과 항목별 질문에서는 지갑을 설명하고 `Black`, `Aldebran`을 출력했습니다. 그러나 사용자가 지정한 다섯 줄 프롬프트는 치수 반복으로 실패했고, 항목별 질문에서도 형태와 스티커에 의심스러운 응답이 나왔습니다. 단순히 JSON 문법만 고치면 해결되는 A 상태가 아닙니다. 현 프로젝트의 기본 추출기는 Qwen을 유지하는 편이 타당합니다. Smol의 후처리 JSON은 **사람 검토 전 후보 결과**로만 취급합니다.

이 판단은 두 상품 사진에 한정한 사용 가능성 판단이며, 사람의 정답 라벨 기반 정확도 평가는 아닙니다. 여기서 실험을 종료합니다.

## 1. 원인 구분

| 원인 후보 | 실제 확인 내용 | 판단 |
|---|---|---|
| 이미지를 전혀 인식하지 못함 | 사진마다 다른 치수·문자를 출력하고, 짧은 설명에서 leather wallet 및 로고 색을 언급. 흰색 입력은 다른 숫자 반복 응답 | 이미지 정보가 전달되고 일부 인식됨. 세부 특징의 정확성은 보장 못 함 |
| 특징은 맞지만 JSON 문법만 문제 | 기존 응답은 `json.loads` 가능한 JSON이지만 `$defs`, `properties`, `required` 등 스키마 내용을 복제 | 단순 JSON 문법 오류가 아니라 지시 수행·출력 내용 문제 |
| Qwen용 스키마가 복잡함 | 긴 스키마에서는 복사, 다섯 줄 형식에서도 반복. 한 문장/단일 질문에서는 짧은 응답 | 구조화 지시의 복잡성에 민감하다는 근거. 스키마 길이만의 인과관계가 확정된 것은 아님 |
| max_new_tokens 부족 | 기존 응답은 436~440/512토큰, 정상 종료. 새 다섯 줄 응답은 반복하다 512토큰 상한 도달 | 기존 실패의 원인은 아님. 새 다섯 줄에서는 반복 때문에 잘림. 상한 증가가 반복 문제를 해결하지는 않음 |
| 전처리·채팅 템플릿 오류 | 공식 Processor, `User:<image>...Assistant:` 경계, 이미지 tensor, 입력 토큰 이후 생성분만 decode 확인. 입력 PIL은 RGB 640×640 | 입력 누락·프롬프트 전체를 응답으로 잘못 decode하는 오류는 발견 못 함. 모델 내부 확대/17개 패치와 상품 합성 이미지의 영향은 분리 검증하지 않음 |

첫 이미지의 기본 응답 예:

```text
11 cm, N.D.M. Leather, 9 cm, Aldebran, 1 cm, 9 cm, 1 cm, 9 cm, ...
```

둘째 이미지는 `11 cm, 1 cm, Premium Nappa Leather, 9 cm, 1 cm, ...`를 반복했습니다. 이미지가 달라지면 일부 문자도 달라집니다. 다만 지갑 표면과 주변 상품 설명을 구분해 읽는다는 증거는 아닙니다.

## 2. 실험 조건과 원문

입력은 기존 비교에 사용한 다음 두 이미지와 **동일 SHA-256의 복사본**입니다.

- `01-3_jpg.rf.2c92f3d4c06faa707170580d4bce9f0a.jpg`
- `01-4_jpg.rf.806569195871cc3fa06f96ae0f8ed205.jpg`

기존 EXIF/RGB 전처리, 긴 변 상한 768을 그대로 사용했습니다. 실제 입력 크기는 640×640입니다. 모델은 프로세스별 한 번 로딩했습니다. 패키지를 재설치하지 않았습니다.

### 사용자가 지정한 프롬프트 그대로

[프롬프트 원문](../data/output/smol-diagnosis/20261102-175246-ad40183d/prompt.txt)을 두 이미지에 각각 두 번 적용했습니다. 4회 모두 다섯 항목 형식 대신 OCR 문자열을 반복하여 변환에 실패했습니다. 흰색 대조 이미지도 `1.0000...`를 반복하며 상한에 도달했습니다. 빈 이미지에도 unknown으로 답할 수 있다고 가정하면 안 됩니다.

[응답·시간·토큰·템플릿 전체 기록](../data/output/smol-diagnosis/20261102-175246-ad40183d/records.json), [첫 이미지 원문](../data/output/smol-diagnosis/20261102-175246-ad40183d/01-simple-repeat1.raw.txt), [둘째 이미지 원문](../data/output/smol-diagnosis/20261102-175246-ad40183d/02-simple-repeat1.raw.txt).

### 한 문장 설명

`Describe this image in one short sentence. Do not guess unreadable text.`

```text
01-3: A leather wallet with a gold embossed logo and a black leather strap.
01-4: A leather wallet with a white logo and a black pouch is shown.
```

첫 응답의 `black leather strap`, 둘째 응답의 `black pouch` 등이 실제 무엇을 가리키는지는 사용자 검증이 필요합니다. 설명이 자연스럽다는 이유로 정확하다고 처리하지 않았습니다. 두 응답은 17/15토큰에서 정상 종료했습니다.

### 한 항목씩 별도 질문

동일 이미지에 색상·형태·로고·스티커 모양·스티커 위치를 각각 따로 물었습니다. 각 질문의 상한은 64토큰이며 실제 출력은 2~5토큰이어서 잘리지 않았습니다.

| 항목 | 01-3 실제 응답 | 01-4 실제 응답 |
|---|---|---|
| 색상 | Black | Black |
| 외형 | Square. | Circle. |
| 지갑 표면 문자 | Aldebran. | Aldebran. |
| 스티커 모양 | rectangle. | circle. |
| 스티커 위치 | Top right. | Top right. |

[질문·원문·템플릿 기록](../data/output/smol-diagnosis/20261102-175433-e53dab23/records.json).

원본은 치수선, 원형 확대 보기, 옆면 보기를 함께 배치한 상품 이미지입니다. 지갑 외형·스티커와 이런 그래픽을 혼동했을 가능성이 있습니다. `Circle`, `Top right`를 정확한 특징으로 자동 승인하지 않았습니다. 스티커 질문 자체의 전제에 끌려 답하는 영향도 배제하지 못했습니다.

## 3. Python 변환과 기존 스키마

새 [진단 스크립트](../scripts/diagnose_smolvlm.py)의 `parse_features`는 정확한 다섯 라벨을 요구합니다. 누락·중복·추가 줄·지원하지 않는 색상·모순된 스티커 값·전부 unknown인 출력은 실패로 처리합니다. 토큰 상한에 닿은 응답도 변환하지 않습니다. 실패 원문은 그대로 남깁니다.

명시된 색상·형태·문자·스티커 값만 옮기고, 질문하지 않은 category는 unknown, wallet_type은 null, materials와 distinctive_features는 빈 배열로 둡니다. 스티커의 명시적 none과 unknown을 구분합니다. 기존 Pydantic 스키마를 수정하지 않았습니다. **텍스트를 충실히 옮기는 변환이며 시각적 사실 검증기는 아닙니다.**

다섯 개별 응답을 결합한 후보 JSON은 두 이미지 모두 스키마 검증을 통과했습니다. 모델의 잘못된 인식까지 고쳐지지는 않습니다.

첫 이미지 후보:

```json
{
  "category": "unknown",
  "colors": ["black"],
  "shape": "Square",
  "wallet_type": null,
  "materials": [],
  "logos_or_text": ["Aldebran"],
  "sticker_status": "present",
  "stickers": [{"shape": "rectangle", "position": "Top right"}],
  "distinctive_features": []
}
```

둘째 이미지 후보:

```json
{
  "category": "unknown",
  "colors": ["black"],
  "shape": "Circle",
  "wallet_type": null,
  "materials": [],
  "logos_or_text": ["Aldebran"],
  "sticker_status": "present",
  "stickers": [{"shape": "circle", "position": "Top right"}],
  "distinctive_features": []
}
```

[결합 원문과 후보 JSON](../data/output/smol-diagnosis/20261102-175433-e53dab23/qa-conversions.json)은 `visual_accuracy=user_review_required`로 저장했습니다. 검증된 정답이나 운영 결과 폴더로 승격하지 않았습니다.

## 4. Qwen과 비교

Qwen은 동일 이미지 해시의 **이전 실측을 재사용**했습니다. 이번 작업에서 Qwen을 재실행하거나 변경하지 않았습니다. 시간 차이는 같은 시점의 통제 실험으로 해석할 수 없습니다.

| 이미지 | 방법 | 이미지당 추론 | 최대 할당 VRAM | 출력/변환 검증 |
|---|---|---:|---:|---|
| 01-3 | 기존 Qwen NF4 | 17.068 / 16.058초 | 1.806GiB | JSON 2/2 통과 |
| 01-4 | 기존 Qwen NF4 | 17.231 / 16.989초 | 1.806GiB | JSON 2/2 통과 |
| 01-3 | 기존 Smol 긴 스키마 | 14.517 / 13.861초 | 1.556GiB | JSON 문법 유효, 특징 스키마 0/2 |
| 01-4 | 기존 Smol 긴 스키마 | 14.015 / 13.481초 | 1.556GiB | JSON 문법 유효, 특징 스키마 0/2 |
| 01-3 | Smol 사용자 다섯 줄 프롬프트 | 14.627 / 13.460초 | 1.413GiB | 형식 0/2, 각 512토큰 반복 |
| 01-4 | Smol 사용자 다섯 줄 프롬프트 | 13.671 / 13.491초 | 1.413GiB | 형식 0/2, 각 512토큰 반복 |
| 01-3 | Smol 한 문장 | 1.443초 | 1.413GiB | 자연어 설명, JSON 평가 대상 아님 |
| 01-4 | Smol 한 문장 | 1.398초 | 1.413GiB | 자연어 설명, JSON 평가 대상 아님 |
| 01-3 | Smol 개별 질문 5개 합계 | 6.825초 | 1.413GiB | Python 변환 1/1, 내용은 미검증 |
| 01-4 | Smol 개별 질문 5개 합계 | 5.604초 | 1.413GiB | Python 변환 1/1, 내용은 미검증 |

Smol 이번 로딩은 약 2.090초/2.045초입니다. 추론 시간은 Processor·전송·생성·디코드 및 해당되는 파싱을 포함하며 CUDA 동기화를 적용했습니다. 개별 질문 합계는 다섯 번 이미지 처리와 추론을 합친 값이고 마지막 결합 검증 시간은 제외됩니다. 서로 출력 내용의 양과 성공 여부가 달라 단순 속도 순위로 해석하면 안 됩니다. VRAM은 PyTorch 할당량으로 다른 앱 메모리는 제외됩니다.

| 특징 | Qwen 이전 출력 | Smol 개별 질문 출력 | 검토 상태 |
|---|---|---|---|
| 01-3 색상 | black, brown | Black | 부분 정보 차이, 사용자 확인 필요 |
| 01-4 색상 | black | Black | 일치하나 정답 자동 승인 안 함 |
| 01-3/01-4 형태 | rectangle | Square / Circle | 명백한 출력 차이, 사용자 확인 필요 |
| 01-3/01-4 로고 | Aldebran | Aldebran | 일치하나 문자 정답 확인 필요 |
| 01-3 스티커 | absent | rectangle, Top right | 서로 충돌, 사용자 확인 필요 |
| 01-4 스티커 | rectangle, bottom | circle, Top right | 서로 충돌, 둘 다 정답으로 간주 안 함 |

Qwen 출력도 정답 라벨이 아닙니다. 특히 상품 설명·확대 원을 스티커나 물체의 특징으로 오인하는지는 두 모델 모두 사람이 확인해야 합니다.

[원본·Qwen·수정 전 Smol·수정 후 Smol 나란한 기록](../data/output/smol-diagnosis/20261102-175433-e53dab23/paired-results.json), [이전 비교 보고서](../data/output/comparison-smolvlm/20261102-174231-4433b918/REPORT.md).

## 5. 변경 및 검증 범위

추가 파일은 `scripts/diagnose_smolvlm.py`, `tests/test_smol_parser.py`, 이 문서이며 결과는 `data/output/smol-diagnosis/`에 별도 저장했습니다. 기존 비교 스크립트·Qwen 코드·Pydantic 스키마를 수정하지 않았습니다.

파서 테스트 9개가 통과했습니다. 두 실행의 `preservation.json` 모두 `unchanged: true`, `changed: []`입니다. 기존 Qwen 소스·설정·문서·가중치·기존 최상위 결과의 해시 보존을 확인했습니다. 새 패키지 설치나 Fine-tuning은 없었습니다.

재현은 다음 명령으로 가능하지만 이번 진단은 이미 실행 완료했으며, 전체 이미지 실험은 하지 않았습니다.

```powershell
$env:HF_HUB_OFFLINE="1"
.\.venv-smol\Scripts\python.exe -m scripts.diagnose_smolvlm
.\.venv-smol\Scripts\python.exe -m scripts.diagnose_smolvlm --qa-only
```

남은 미검증 사항: 사람 정답 라벨, 더 다양한 실제 사진, 스티커 유무 판별의 신뢰성, 정밀한 색상·모양·문자 정확도, 전처리 패치 수 변경 효과, 전체 42장 및 장시간 성능. 이번 사용 가능성 판단 범위에서는 추가 확장하지 않았습니다.
