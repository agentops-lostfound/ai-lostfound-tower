# CPU MiniLM 후보 매칭

Qwen이 저장한 물체 특징을 문장으로 만들고 영어 사용자 설명과 임베딩 유사도로 비교합니다. 모델은 `sentence-transformers/all-MiniLM-L6-v2`, 실행은 FastEmbed의 ONNX 모델과 `CPUExecutionProvider`로 고정합니다. Qwen/YOLO 코드와 팀 공통 계약은 바꾸지 않습니다. 벡터 DB와 외부 추론 API는 사용하지 않습니다.

## 실행

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
- 지금은 의미 유사도 순위만 구현했습니다. 색상·브랜드의 별도 가중 점수와 명시적 모순 처리, 사용자 확인 흐름은 아직 연결하지 않았습니다.
- 코사인 유사도는 정답 확률이 아니며 최고점만으로 물품을 확정하거나 로봇을 움직이지 않습니다.

이 모델은 영어용입니다. 한국어 문자를 포함한 입력은 오류로 거부합니다. **한국어→영어 번역/특징 정규화는 아직 미구현**이며, 현재 CLI에는 영어로 입력해야 합니다. 번역 단계가 생기면 그 지연도 전체 시간에 더해야 합니다.

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

실사진·crop·원본 출력 JSON·프로세스 로그·절대 로컬 경로는 보고서 배포 파일에 포함하지 않았습니다. 평가 JSON은 이 보고서를 재검토할 수 있도록 선택한 특징과 질의·점수만 포함합니다. 긍정 설명은 Qwen 저장값을 보고 작성했으며, 중복 실행과 단일 후보도 있으므로 정량 실물 식별 정확도로 해석하면 안 됩니다. 한국어 문장은 사람이 읽기 위한 설명이고 실제 임베딩 입력은 영어입니다. 현재 모듈은 거절·추가질문 없이 순위만 반환합니다.
