# DeepL 번역 API 실험

한국어 사용자 문장만 DeepL로 전송하고, 영어 조건 추출·MiniLM 후보 비교는 기존 로컬 코드를 사용한다. 사진·Qwen 후보·좌표는 요청에 포함하지 않는다. 이 경로는 외부 API 사용이며 로컬 번역 옵션도 유지한다.

실제 비교는 유효한 DeepL API 키가 필요하다. 일반 DeepL 웹 번역기 로그인과 API 인증은 다르다. 현재 키 없이 실행 결과를 만들거나 API 성능을 주장하지 않았다. 단위 테스트는 가짜 응답으로 연결 동작만 검증한다.

## 키 설정과 단일 실행

DeepL API 계정에서 발급한 키를 본인 PowerShell에 입력한다. 아래 입력은 화면과 명령 기록에 키 값을 표시하지 않는다. .env는 읽지 않는다.

```powershell
cd C:\Users\user\AI-LostFound\team-repo
$taskTranslationKey = Read-Host 'DeepL API key' -AsSecureString
$env:DEEPL_AUTH_KEY = [System.Net.NetworkCredential]::new('', $taskTranslationKey).Password
$env:PYTHONIOENCODING = 'utf-8'

& ..\.venv-query\Scripts\python.exe -u -m matching.demo_query_parser `
  --mode translate --translator deepl `
  --output-dir outputs/matching/translation_demo_deepl `
  --candidates outputs/vision/db05d2b6f5a54d40837f0213969e2f55/result_with_qwen.json
```

API에는 --offline을 사용하지 않는다. Free 키의 :fx 접미사에 따라 공식 Free endpoint를 선택하고 그 외에는 Pro endpoint를 사용한다. 모델명·가중치는 공급자가 관리하므로 고정한 로컬 모델과 동일한 재현성을 주장하지 않는다. 출력 HTML에는 원문·실제 API 번역·코드 추출·후보 비교·판정이 표시된다. 인증 헤더·키는 기록하지 않는다.

## 같은 20문장 평가

```powershell
& ..\.venv-query\Scripts\python.exe -u -m matching.evaluate_translation --translator deepl
```

실행하면 기존 20개 문장을 문장별 1회씩 요청한다. 사용량 과금·한도는 계정 계약을 따른다. 자동 재시도·자동 로컬 폴백은 하지 않는다. HTTP 오류나 타임아웃은 명시적으로 실패 처리하며, 타임아웃 후 과금 여부가 불명확할 수 있다. 결과는 outputs/matching/translation_20_deepl/REPORT.html 및 JSON에 저장해 기존 두 모델 결과와 구분한다.

키가 없는 경우 요청 전에 실패한다. 연결 구현 완료와 실제 API 평가 완료는 구분한다. requires_review는 유지하며, API를 바꿔도 코드의 부정 범위·색 대상 처리와 임베딩의 자유 문장 부정 구별 문제는 남는다.

공식 근거: [인증·Free/Pro endpoint](https://developers.deepl.com/docs/getting-started/auth), [번역 요청 형식](https://developers.deepl.com/api-reference/translate/request-translation).
