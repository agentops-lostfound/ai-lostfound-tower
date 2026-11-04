# CPU MiniLM 후보 매칭

Qwen이 저장한 물체 특징을 문장으로 만들고 사용자 설명과 임베딩 유사도로 비교합니다. 모델은 `sentence-transformers/all-MiniLM-L6-v2`, 실행은 FastEmbed의 ONNX 모델과 `CPUExecutionProvider`로 고정합니다. 기본 한국어 전처리는 로컬 규칙·사전과 OPUS-MT를 사용합니다. 외부 API 비교는 별도 선택 옵션이며 벡터 DB는 사용하지 않습니다.

## 실행

2026-11-04 잠정 기준은 **한국어 선추출 → 사전 변환 → 자유 구절 번역**입니다. --parse-korean과 전처리 데모의 기본 경로에 반영했습니다. [채택 근거·실행·한계](../docs/reports/2026-11-04-korean-first-decision.md)를 참고하세요. 자동 확정 검토 제한은 유지합니다.

번역 API를 비교하려면 [DeepL API 실험 방법](API_TRANSLATION.md)을 참고하세요. 인증키는 로컬 환경변수로 설정하고 별도 --translator deepl 경로를 선택합니다.

한국어 설명 자동 전처리는 선택 기능입니다. [별도 환경·실행·검증 방법](QUERY_PARSER.md)을 참고하세요. 기존 영어 입력 방식에는 추출 모델이 필요 없습니다.

저장소 루트, 비전 Python 3.11 환경에서:

```powershell
python -m pip install -r matching/requirements.txt
python -m matching.rank_items `
  --query "A dark blue phone with a cartoon sticker on the back" `
  --candidates "outputs/vision/<실행ID>/result_with_qwen.json"
```

현재 PC에서 확인한 결과 파일로 재실행:

```powershell
& ..\.venv-vision\Scripts\python.exe -m matching.rank_items `
  --query "A white phone with two cameras and damage on its back" `
  --candidates outputs/vision/262a3fbb20e1489495aa30dd55cf18e9/result_with_qwen.json `
  --offline --benchmark 20
```

첫 실행은 공개 ONNX 모델을 다운로드하므로 인터넷이 필요합니다. 이후 --offline으로 캐시를 사용합니다. 원본 사진과 특징은 외부 추론 API에 전송하지 않습니다. 모델/후보 벡터 캐시는 `.cache/matching/`, 순위 결과는 `outputs/matching/<고유ID>/ranking.json`이며 Git 제외입니다. --output으로 저장 위치, --threads로 CPU 스레드 수를 지정합니다.

## 입력과 출력

- 입력은 일반 검출 result.json이 아닌 **Qwen까지 실행한 result_with_qwen.json**입니다.
- `objects[].qwen.status=ok`인 실제 특징만 후보로 사용합니다. 실패·미완료 또는 관찰 특징이 없는 후보는 이유와 함께 제외합니다.
- YOLO class_name은 의미 비교 문장에 넣지 않습니다. USB를 cell phone으로 검출한 이름을 매칭 근거로 사용하지 않습니다.
- 출력에는 물체 ID, crop 경로, 기존 좌표, 원본 특징, 비교 문장, cosine_similarity가 있습니다.
- CLI는 색·품목·스티커 점수와 설정 기반 판정을 추가합니다. 브랜드 별도 비교와 실제 확인 질문 UI는 아직 없습니다.
- 코사인 유사도는 정답 확률이 아니며 최고점만으로 물품을 확정하거나 로봇을 움직이지 않습니다.

MiniLM은 영어용이라 한국어 문장을 직접 비교하면 거부합니다. 기본 CLI는 영어 입력을 사용합니다. 한국어 자동 변환은 별도 환경에서 --parse-korean을 지정하는 [실험 전처리](QUERY_PARSER.md)로 추가했으며 모델 로딩·변환 시간이 더해집니다.

## 반복 요청과 캐시

`MiniLMRanker` 인스턴스 하나를 유지하고 `prepare(candidates)` 후 `rank(query)`를 반복 호출하면 모델을 재로딩하지 않습니다. 후보 텍스트·모델 ID·FastEmbed 버전이 동일하면 저장 벡터를 재사용합니다. Qwen 특징이 바뀌면 새 벡터를 계산합니다. CLI를 실행할 때마다 프로세스와 모델은 새로 시작하므로 반복 요청의 수 ms 수치와 CLI 전체 시간은 다릅니다.

## 2026-11-03 로컬 검증

환경: Windows Python 3.11.18, FastEmbed 0.8.1, ONNX Runtime 1.31.1, CPU 2 threads, 출력 384차원.

실제 Qwen 스마트폰 2개 결과를 사용했습니다.

| 입력 설명 | 1위 | 유사도(0번 / 1번) |
| --- | --- | --- |
| dark blue phone with a cartoon sticker | object_0 | 0.721 / 0.546 |
| white smartphone with two camera lenses and rear damage | object_1 | 0.272 / 0.478 |
| navy mobile device with an animated character decal | object_0 | 0.512 / 0.369 |
| pale handset with a pair of rear cameras | object_1 | 0.297 / 0.332 |

원래 JSON과 단어가 다른 문장에서도 목표 후보가 1위였지만, 마지막 예시는 점수 차가 약 0.034로 작습니다. 2개 물체와 수작업 질의 4개만의 연결 시험이며 일반 정확도 보장은 아닙니다. 잘못된 Qwen OCR·재질·스티커 정보는 그대로 오류를 유발할 수 있습니다.

- 최초 다운로드/모델 초기화 약 15.13초, 후보 임베딩 2개 계산 약 21.9ms.
- 다운로드된 모델을 오프라인으로 새로 로딩한 실행의 초기화 약 1.05초. 후보 벡터 2개 캐시 적중.
- 같은 모델 인스턴스에서 같은 영어 질의를 20회 반복한 warm 요청 중앙값 약 **3.70ms**. 질의 임베딩+순위 계산 포함, 번역·Qwen·파일 저장·모델 로딩은 제외.
- 초기화와 벤치마크 20회를 포함한 CLI 내부 전체 약 1.19초. Python 프로세스 시작 자체는 이 계측에 포함되지 않습니다.
- 실행별 원본 측정값: outputs/matching/minilm_phone_trial.json, minilm_white_phone_trial.json, paraphrase_trials.json (Git 제외).
- 전체 unittest 148개 실행: 실패/오류 0개, DB 시험 1개 제외. 후보 제외·중복 ID·벡터 검증·캐시 변경 감지·한국어 입력 거부를 확인했습니다. pip check 통과.

추가 모델이나 양자화·전처리를 바꾸면 벡터 캐시 식별자도 변경해야 합니다. 패키지 고정은 재현을 돕지만 모델 파일 upstream revision까지 고정한 실험은 아닙니다.

공식 근거: [FastEmbed](https://github.com/qdrant/fastembed), [MiniLM 모델 카드](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).

## 전체 저장 결과 점검 보고서

- [팀 공유용 평가 보고서](reports/QWEN_AUDIT.md): 개별 특징 17개·질의 34개, 모든 후보 점수와 해석
- [HTML 보고서](reports/QWEN_AUDIT.html): 다운로드 후 브라우저에서 열기
- [평가 질의·점수 JSON](reports/qwen_audit.json): 공유용으로 정리한 선택 평가 데이터

실사진·crop·원본 출력 JSON·프로세스 로그·절대 로컬 경로는 보고서 배포 파일에 포함하지 않았습니다. 평가 JSON은 이 보고서를 재검토할 수 있도록 선택한 특징과 질의·점수만 포함합니다. 긍정 설명은 Qwen 저장값을 보고 작성했으며, 중복 실행과 단일 후보도 있으므로 정량 실물 식별 정확도로 해석하면 안 됩니다. 한국어 문장은 사람이 읽기 위한 설명이고 실제 임베딩 입력은 영어입니다. 이 보고서는 기존 의미 유사도 순위 실험이며 아래의 새 판정 정책을 평가한 결과가 아닙니다.

## 판정 기준 조정

[`configs/matching.yaml`](configs/matching.yaml)을 수정하면 다음 CLI 실행부터 적용됩니다. 다른 설정은 `--config 경로`로 지정합니다. 설정과 사용한 조건은 출력 JSON에도 저장됩니다. 기본값은 검증 전 실험값입니다.

- `reject_category_mismatch`: 알려진 품목 불일치 후보 제외 여부.
- `reject_clear_color_mismatch`: 색 비교 점수가 0인 후보 제외 여부. 등록하지 않은 다른 색 조합은 0이므로 필요한 유사색 쌍을 직접 추가해야 합니다.
- `weights`: category/color/sticker/semantic 가중치. 합계는 자동 정규화하며 각 값은 0~1, semantic은 양수입니다.
- `color_similarity`: 유사색 쌍 점수. 양방향 적용하며 동일한 색은 1, 미등록 조합은 0입니다. 부분 일치 점수는 min_attribute_score와 비교합니다.
- `decision.min_score`: 최종 점수 하한.
- `decision.min_margin`: 제외되지 않은 1·2위의 최종 점수 차이 하한. 후보가 하나면 점수·속성 조건만 적용합니다.
- `decision.min_attribute_score`: 각 요청 속성의 최소 점수. 기본 0.8이라 navy↔dark blue(0.9), wallet↔card_wallet(0.8)는 다른 조건과 최종 점수도 만족하면 확정 가능합니다. 서로 비슷한 후보가 있으면 min_margin으로 보류합니다.
- `category_similarity`: 품목 관계 점수. wallet↔card_wallet을 호환 관계로 두며, 다른 품목을 전부 합치지는 않습니다.
- `decision.min_attribute_coverage`: 명시한 조건 중 후보에서 관찰된 조건의 최소 비율. 기본 1.0이라 요청 속성이 unknown이면 보류합니다.

구조화 조건은 [`configs/query.example.json`](configs/query.example.json)을 복사해서 작성합니다. 지원 키는 `category`, `colors`(배열), `sticker_status`(present/absent/unknown), `free_text`(영어 세부 특징)입니다. 미언급 조건은 생략하거나 unknown으로 두고, 색 미언급은 빈 배열로 둡니다. 색·품목·스티커 유무는 앞의 필드에 넣고, free_text에는 카메라·스티커 모양/위치·흠집·무늬 등만 넣습니다. 자연어에서 조건을 자동 추출하지 않습니다.

```powershell
& ..\.venv-vision\Scripts\python.exe -m matching.rank_items `
  --query "A white phone with two cameras and damage on its back" `
  --query-features matching/configs/query.example.json `
  --config matching/configs/matching.yaml `
  --candidates outputs/vision/262a3fbb20e1489495aa30dd55cf18e9/result_with_qwen.json `
  --offline
```

현재 CLI는 품목·색 필터를 먼저 적용합니다. 통과 후보만 shape/materials/logos_or_text/distinctive_features/스티커 세부 설명을 임베딩하며, category/colors/스티커 없음 필드는 임베딩 문장에서 제외합니다. distinctive_features 안에 색 표현이 섞여 있으면 그 문장은 유지합니다. 음수 코사인은 최종 결합에서 0으로 처리하고 원본 cosine_similarity는 보존합니다. 사용자가 명시한 조건과 실제 계산한 semantic만 가중 평균합니다. 요청했지만 후보에서 unknown인 속성은 0점으로 남기고 별도로 표시하며, 명확한 불일치로 제외하지는 않습니다.

free_text가 비어 있으면 임베딩 모델을 로딩하지 않고 속성만으로 판단합니다. free_text를 요청했는데 해당 후보의 자유 특징이 없으면 보류합니다. 제외된 후보 또는 의미 비교를 생략한 후보의 cosine_similarity는 null입니다. --query는 원문 기록이고, --query-features가 있으면 그 안의 조건과 free_text가 실제 판정 입력입니다. 조건 파일이 없으면 --query 전체를 자유 문장으로 비교하되 구조화 조건이 없으므로 확정하지 않습니다. 기존 MiniLMRanker API는 원래 의미 유사도 실험용으로 유지합니다.

출력의 `decision.status`는 matched/needs_confirmation/no_match입니다. selected_id는 matched일 때만 채웁니다. 속성 점수 하한 미달, 부족한 관찰, 낮은 최종 점수 또는 작은 순위 차이는 보류합니다. 구조화 조건 없이 기존 --query만 주면 순위는 반환하되 확정하지 않습니다. Qwen이 확신 있게 틀린 속성을 기록한 경우는 자동으로 알아낼 수 없으므로 실제 사진으로 정책을 검증해야 합니다. 로봇 명령이나 확인 질문 UI는 실행하지 않습니다.

색 동의어는 `policy.py`의 ALIASES에서 관리합니다. 이 사전 자체는 구조화 조건의 일부 한국어 색 이름만 정규화합니다. 문장 추출·영어 변환은 별도 선택 기능인 query_parser.py가 담당합니다.

## 필터와 자유 특징 임베딩 비교 결과

[변경 내용·실험 결과 요약 보고서](reports/MATCHING_UPDATE.md): 푸시한 기능, 기존 대비 결과, 후속 실제 사진 시험과 남은 한계.

[새 정책 비교 보고서](reports/HYBRID_COMPARISON.md)와 [조건·점수 JSON](reports/hybrid_comparison.json)을 참고하세요. 같은 34개 질문에서 이전 정책의 정상 설명 10개 확정·7개 보류가 16개 확정·1개 보류로 바뀌었고, 모순 설명 17개는 모두 no_match였습니다. 조건과 자유 문장은 사람이 분리했고 Qwen 저장값을 정답 근거로 삼았으므로 실제 사용자 정확도로 해석하지 않습니다. 남은 보류 사례는 사용자가 실제 폰이라고 확인했지만 Qwen category가 other였던 경우입니다. 이 사례 때문에 기준을 낮추지는 않았습니다.
