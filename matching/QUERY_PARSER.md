# 한국어 설명 전처리 (실험 기능)

## 한국어에서 먼저 추출하는 대안

2026-11-04 잠정 채택: 한국어 모델을 추가 호출하지 않고 규칙으로 원문 근거·품목·색·스티커 유무를 추출하며, 손상·위치 같은 연결 구절만 OPUS-MT에 보냅니다. 원문의 고유 글자는 직접 보존합니다. 데모 기본 mode, --parse-korean의 기본 backend, 20문장 평가의 기본 translator를 모두 korean-first로 맞췄습니다. [실험 결과](reports/KOREAN_FIRST_TRIAL.md)와 [잠정 채택 보고서](../docs/reports/2026-11-04-korean-first-decision.md)를 참고하세요. 자동 확정 제한은 유지합니다.

외부 API 비교 경로도 추가했습니다. [DeepL 키 설정·실행·20문장 평가](API_TRANSLATION.md)를 참고하세요. 키가 있어야 실제 API 평가가 가능하고, 기존 오프라인 모델 시험과 구분합니다.

## 자유 구절 번역 모델: OPUS-MT / 기존 통번역 비교 경로

잠정 채택 경로는 한국어 사전으로 속성을 먼저 결정하고 Helsinki-NLP/opus-mt-ko-en으로 자유 구절을 번역합니다. 이전 통번역 비교 경로는 --mode translate --translator opus 또는 --parse-korean --parser-backend opus로 선택합니다. OPUS는 CPU, 빔 4를 사용하며 공식 모델 카드의 라이선스 표시는 Apache-2.0입니다. 가중치·토크나이저는 .cache/translation_opus/model에 일반 파일로 저장합니다.

같은 20문장과 같은 코드 규칙·후보 데이터에서 조건 전체 일치가 10/20→14/20, 변환 중앙값이 약 2.52초→0.51초로 개선됐습니다. 번역 정확도 70%를 의미하지 않으며 [오류·상세 비교](reports/OPUS_TRANSLATION_COMPARISON.md)를 참고하세요. requires_review 제한은 유지합니다.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& ..\.venv-query\Scripts\python.exe -u -m matching.demo_query_parser `
  --offline --mode translate --translator opus `
  --output-dir outputs/matching/translation_demo_opus `
  --candidates outputs/vision/db05d2b6f5a54d40837f0213969e2f55/result_with_qwen.json
```

데모의 기존 direct 모드는 Qwen 직접 JSON 추출 비교용으로 남겼습니다. 이전 통번역 모델은 --mode translate --translator qwen으로 지정합니다. rank_items에서는 --parse-korean --parser-backend qwen-direct 또는 qwen-translate로 과거 경로를 선택합니다. 20문장 평가는 --translator opus/qwen을 명시할 수 있고 기본 출력 폴더도 모델별로 분리됩니다. 이하의 초기 Qwen 설명과 시험 결과는 과거 실험 기록입니다.

**현재 0.6B 모델의 실제 예문 시험에서 색·스티커 환각이 확인돼 자동 확정용으로 채택하지 않았습니다.** parse 결과는 requires_review=true를 반환하고 --parse-korean 경로의 최종 판정은 보류합니다. 기존 수동 조건 JSON 경로는 유지합니다. 더 나은 모델/추출 방식과 독립 평가를 거친 뒤에만 이 제한을 재검토해야 합니다.

[실제 예문 시험 결과](reports/QUERY_PARSER_TRIAL.md): 검사 필드 전체 일치 2/8, 변환 중앙값 약 12.12초. 자유 문장의 의미는 별도 검토가 필요합니다.

[통번역 → 코드 추출 20문장 시험](reports/TRANSLATION_20_TRIAL.md): 기존 11개 후보 그룹에 220회 비교. 검사 필드 일치 10/20, 변환 중앙값 약 2.52초이며 번역 오류와 파손 부정문 오선택이 남았습니다.

`query_parser.py`는 후보 Qwen 값을 보지 않고 사용자 문장에서 품목·색·스티커 유무와 영어 세부 특징을 추출합니다. 비전 Qwen과 별개인 **Qwen/Qwen3-0.6B 텍스트 모델**을 CPU에서 실행합니다. 학습 없이 프롬프트로 변환하며, 코드로 출력 형식과 표준값을 검사합니다. 형식 검사는 내용의 사실성·번역 정확성을 보장하지 않습니다.

기존 영어/조건 JSON 경로는 추가 모델 없이 유지됩니다. 원본 문장, 추출값, 확인 필요 표시, 출력 토큰 수와 처리 시간을 저장합니다. 형식 오류·출력 길이 초과는 실패로 종료하며 임의 복구나 자동 재시도를 하지 않습니다. 확인 필요 표시가 있으면 매칭도 보류합니다.

## 환경과 독립 실행

별도 Python 3.11 가상환경에서 `python -m pip install -r matching/requirements-query.txt`를 실행합니다. 첫 실행에는 공개 모델 다운로드가 필요하며 이후 --offline으로 캐시만 사용합니다. CPU float32 모델이므로 가중치·실행 메모리와 시작 시간이 추가됩니다. 캐시 `.cache/query_parser`는 Git 제외이며 사용자 문장은 로컬 추론으로 처리합니다.

현재 PC에는 `..\.venv-query`를 만들고 기존 CPU 비전 패키지를 로컬 .pth로 참조하도록 구성했습니다. 이 경로는 다른 PC에 복사할 설정이 아닙니다. 새 PC에서는 위 requirements를 설치하세요.

```powershell
& ..\.venv-query\Scripts\python.exe -m matching.query_parser `
  --text "곤색 카드지갑인데 뒤에 별 스티커가 있어요" `
  --output outputs/matching/parsed_query.json --offline
```

UTF-8 텍스트 파일은 --text 대신 --input으로 지정합니다. 반환 객체의 features가 기존 매칭 조건입니다. 메인 프로그램에서는 QueryParser 인스턴스를 유지하고 parse(text)를 반복 호출하며 needs_clarification/warnings를 확인해야 합니다. 출력 전체는 메타데이터를 포함하므로 기존 --query-features에 그대로 전달하는 평면 JSON과는 다릅니다.

## 한국어 입력부터 매칭까지

```powershell
& ..\.venv-query\Scripts\python.exe -m matching.rank_items `
  --query "흰색 아이폰인데 뒤에 애플 로고가 있고 카메라가 두 개예요" `
  --parse-korean `
  --candidates outputs/vision/db05d2b6f5a54d40837f0213969e2f55/result_with_qwen.json `
  --offline
```

--parse-korean과 --query-features는 함께 쓸 수 없습니다. 추출 결과는 ranking.json의 parsed_query에 기록합니다. --benchmark는 추출 후 매칭만 반복합니다. 전체 total_seconds에는 추출 모델 로딩과 변환도 포함됩니다. --threads 기본값은 2이며 PyTorch 전역 CPU 스레드 설정에 영향을 줍니다.

## 검증

### 과정을 직접 보는 데모

#### 전체 영어 번역 → 코드 추출 비교 모드

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& ..\.venv-query\Scripts\python.exe -u -m matching.demo_query_parser `
  --offline --mode translate `
  --output-dir outputs/matching/translation_demo `
  --candidates outputs/vision/db05d2b6f5a54d40837f0213969e2f55/result_with_qwen.json
```

같은 query_demo.txt를 읽되 언어 모델은 전체 영어 번역만 한 번 실행합니다. translated_query.py의 규칙으로 영어 품목·색·스티커 유무를 추출하고 번역문 전체를 free_text로 넘깁니다. 자유 문장을 다시 생성하는 모델 호출은 없습니다. 따라서 자유 문장에는 색·품목도 중복 포함되며, 기존 세부 특징 전용 입력과 점수 분포가 달라질 수 있습니다. 기존 direct 모드의 결과 폴더와 분리해 보존합니다.

색·품목 어휘는 제한적이고 부정·불확실성·색의 대상은 일반적인 문장 해석기가 아닌 보수적인 패턴 검사입니다. 복잡한 표현은 정확히 처리하지 못할 수 있어 requires_review 제한은 유지합니다. 생성된 영어를 사람이 확인해야 하며 스키마 통과가 번역 정확성을 뜻하지 않습니다. 결과 HTML은 outputs/matching/translation_demo/REPORT.html입니다.

`matching/configs/query_demo.txt`를 UTF-8로 저장해 입력 문장을 바꿉니다. 저장소 루트에서 아래를 실행하면 터미널에 단계별 출력이 나오고 HTML에도 같은 실행 기록이 저장됩니다.

```powershell
$env:PYTHONIOENCODING = 'utf-8'
& ..\.venv-query\Scripts\python.exe -u -m matching.demo_query_parser `
  --offline `
  --candidates outputs/vision/db05d2b6f5a54d40837f0213969e2f55/result_with_qwen.json
```

`outputs/matching/query_demo/REPORT.html`을 브라우저에서 열면 한국어 원문 → 실제 프롬프트/입력 토큰 → 모델 원문 출력 → 형식 검증된 JSON → 기대값 비교 → 후보별 점수와 최종 판정을 확인할 수 있습니다. 각 단계가 끝날 때 파일을 갱신하므로 브라우저 새로고침으로 확인할 수 있습니다. 모델 토큰 스트리밍이나 내부 사고 과정 표시는 아닙니다.

--candidates를 생략하면 추출만 실행합니다. 다른 입력 파일은 --input으로 지정하며 출력 위치는 --output-dir로 바꿉니다. 기본 출력 폴더는 재실행 시 덮어쓰므로 기록을 남기려면 다른 폴더를 지정하세요. 기대값 비교는 기존 8개 예문과 원문이 정확하게 일치할 때만 수행하고, 임의 입력은 수동 검토 안내를 표시합니다.

기본 문장은 흰색 아이폰 예문입니다. 이전 시험에서 모델이 미언급 스티커를 present로 추가했던 사례라 expected=unknown과 actual을 비교하면 오류를 볼 수 있습니다. requires_review로 인한 최종 보류와 속성 점수만으로 계산한 policy_decision을 별도로 보여줍니다.

```powershell
& ..\.venv-query\Scripts\python.exe -m matching.evaluate_query_parser --offline
```

configs/query_parser_cases.json의 수작업 예문 8개로 품목·색·스티커 상태·확인 필요 여부를 검사합니다. free_text 의미 충실성은 자동 채점하지 않으므로 직접 검토해야 합니다. 결과는 outputs/matching/query_parser/results.json에 저장합니다. 소규모 시험이며 일반 한국어 이해 성능을 의미하지 않습니다. 모델이 부정·불확실성을 누락하면 형식 검증만으로 감지할 수 없습니다.

모델은 [공식 Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B), Apache-2.0입니다. upstream revision을 고정한 배포가 아니라 모델 선택·CPU 지연·품질을 확인하기 위한 초기 구현입니다.
