# chat-widget — AI 챗봇 위젯 (LF-5, 11/5)

한줄 설명: 어떤 화면이든 **스크립트 한 줄**을 넣으면 "AI챗봇 사용하기" 버튼으로 작은 채팅 창이 열리는 부품이다.
챗봇 두뇌는 관제탑의 `/chat/questions`(정연우 LF-5 챗봇: 이용 안내 RAG + 물건 검색 에이전트, LangGraph)이고, 위젯은 화면만 맡는다.

- 담당: 챗봇·위젯 변재원(보조 정연우) / 붙일 화면 김재민
- 1차 적용 화면: 분실인 웹(`web/lost/`) — **재민 님 웹이 완성됐다고 하면 그때 붙인다**
- 시험 페이지: 관제탑 켠 뒤 `http://127.0.0.1:8100/chat-widget/demo`
- 팀 DB·로봇을 켜지 않는 독립 미리보기: `python -m tools.run_chat_widget_demo` → `http://127.0.0.1:8112/chat-widget/demo`. 승인 문서와 별도 가상 DB만 사용하며 모델을 내려받지 않는다. 다른 포트는 `--port`로 지정한다.
- **11/6 선정 모델로 실행:** `python -m tools.run_chat_widget_demo --engine model --model qwen3:4b-instruct-2507-q4_K_M`. 해당 모델이 로컬 Ollama에 설치되어 있어야 한다. 외부 API·팀 DB·로봇 설정은 불러오지 않는다.
- `--engine model`은 서버 조회 결과와 승인 문서를 근거로 모델이 답변 문장을 직접 작성하고 별도 적합성 검사를 수행한다. 검증 실패·모델 장애는 서버 근거 답변으로 대체한다. 파인튜닝은 하지 않았다. 사용 모델·양자화는 `docs/guidance/chat-model-profile.json`, 비교 분석은 `docs/reports/2026-11-06-sllm-model-selection.md`.
- `--engine legacy`(기본)는 기존 규칙·문단 선택 방식이다. `--model qwen3-vl:2b-instruct`만 주는 실행은 비교용 기존 모드이며 새 모델 대화 모드가 아니다.
- `/chat/health`의 `rag_model_configured`는 모델 설정 여부이며 실제 응답 성공 보장은 아니다. 질문 응답의 `generation_used`와 `generation_status`로 실제 사용 여부를 확인한다.
- 기존 모드의 `semantic_interpretation_used`는 의미 분류 사용 여부다. 새 모드의 `engine=model_rag`, `generation_used=true`는 모델이 작성한 답변이 검사를 통과해 채택됐다는 뜻이다. `grounded_fallback`이면 서버 근거 답변을 표시한다. 모델에 SQL·인증·예약·로봇 실행 권한은 없다.
- 대화 모드는 사용자·도우미 역할을 가진 `turns`를 최대 8개(4쌍) 전달한다. 서버는 역할·개인정보·길이를 검증하고 입력 문맥을 제한한다. 이전 도우미의 말은 본인인증이나 DB 사실의 근거로 사용하지 않는다. ‘대화 지우기’는 두 역할 기록을 함께 지운다.
- 서비스와 무관한 질문·창작·규칙 우회 등은 지원하지 않는 기능으로 안내한다. 인사·감사·분실로 속상한 표현, 짧은 물건 설명과 이어 묻기를 처리한다. 모델 장애 시 기존 문서 안내·입력 확인으로 돌아가며, 알려진 범위 밖 요청 차단은 모델 없이도 작동한다.
- 기존 경로 회귀 검증: `python -m tools.check_chat_communication --model qwen3-vl:2b-instruct`(129개). 새 모델 경로 비교: `python -m tools.compare_chat_models --models qwen3:4b-instruct-2507-q4_K_M --output .cache/model-review.json`(22개 대화). 서로 다른 검증이며 기존 129개 통과를 새 모델 생성 품질로 해석하지 않는다.

## 1. 화면에 붙이는 법 (재민 님, 2줄)
```html
<!-- ① 원하는 버튼에 data-chatbot-open 속성 -->
<button type="button" data-chatbot-open>AI챗봇 사용하기</button>

<!-- ② </body> 바로 위에 한 줄 -->
<script src="/chat-widget/widget.js" defer></script>
```
- 버튼이 없는 화면에는 오른쪽 아래에 동그란 "AI 챗봇" 버튼이 자동으로 생긴다
- 2조봇에게 부탁해도 된다: "web/lost/index.html 의 'AI챗봇 사용하기' 버튼에 web/chat-widget/README.md 1절대로 챗봇 붙여 줘"

## 2. 옵션 (스크립트 태그에 적음, 모두 선택)
| 옵션 | 값 | 뜻 |
| --- | --- | --- |
| `data-launcher` | `auto`(기본) · `always` · `off` | 동그란 버튼: 여는 버튼이 없을 때만 / 항상 / 안 보임 |
| `data-title` | 글자 | 창 제목(기본 "AI 안내 도우미") |
| `data-api` | 주소 | 챗봇 API 서버(기본: 위젯을 내려준 서버 = 관제탑) |
- 코드에서 열고 닫기: `LostFoundChat.open()` · `LostFoundChat.close()` · `LostFoundChat.toggle()`

## 3. 동작 규칙
- 요청은 응답 본문을 받는 시간까지 최대 30초로 제한한다. 시간 초과·잘못된 JSON/응답 구조는 재시도 안내로 표시하고 전송 잠금을 해제한다.
- 실패한 예전 질문을 다시 보내도 다른 질문은 지우지 않는다. 다른 요청이 진행 중이면 재시도 버튼은 대화를 변경하지 않는다.
- 응답이 늦게 도착해도 닫힌 창이나 다른 화면에서 작업 중인 사용자의 포커스를 가져오지 않는다. 전송 중 작성한 다음 질문은 유지한다.
- 500자를 넘는 질문은 자르지 않고 입력란에 남겨 수정하도록 안내한다.
- ‘대화 지우기’는 응답 대기 중에도 작동한다. 진행 중 브라우저 요청을 취소하고 대화·입력 초안·이어 묻기 맥락을 지운다. 이전 답변이 늦게 도착해도 다시 표시하지 않는다. 서버에서 이미 시작한 처리를 되돌리는 기능은 아니다.
- 실패한 질문은 당시 맥락으로 재시도하며, 입력란에 작성 중인 다른 질문은 보존한다.
- 첫 연결 실패·준비 중 상태는 창을 다시 열 때 재확인한다.
- 채팅 창은 화면 디자인을 건드리지 않는다(Shadow DOM 안에 스타일을 가둠). 밝은·어두운 화면 모드를 따라간다
- 넓은 화면: 오른쪽 아래 380px 창 / 휴대폰 폭(480px 이하): 아래에서 올라오는 전체 폭 창(✕ 로 닫음)
- Enter = 보내기, Shift+Enter = 줄바꿈, 한글 조합 중 Enter 는 글자 확정만, Esc = 닫기
- 이전 질문 4개까지 함께 보내 "그건요?" 같은 이어 묻기를 이해한다. 대화는 화면에만 있고 저장하지 않는다(새로 고침하면 사라짐)
- 물건 후보는 품목·색·후보 번호만 보인다(접수 번호·역·사진 없음). "후보는 본인 물건 확정이 아니에요"를 항상 표시
- 지금 물건 검색은 **가상 물건 DB**(배지 "가상 DB 시연"). 실제 팀 DB 검색은 본인인증 세션 검증기(LF-6)가 연결돼야 열린다 — `docs/contracts/chat-search-integration.md`

## 4. 관제탑 쪽 (agents/chat_api.py)
| 주소 | 하는 일 |
| --- | --- |
| `POST /chat/questions` | `{question, history?, suggestion_id?}` → `{answer, agent, status, sources, candidates?, …}` |
| `GET /chat/suggestions` | 추천 질문 |
| `GET /chat/health` | 준비 상태(`ready`, `search_mode`) — 준비 안 되면 창 위쪽에 "준비 중" |
| `GET /chat-widget/widget.js` · `/chat-widget/demo` | 위젯 파일 · 시험 페이지 |
- 환경 설정: `LF_CHAT_ENGINE=model`, `LF_CHAT_MODEL=qwen3:4b-instruct-2507-q4_K_M`로 새 모드를 선택한다. 기존 `LF_CHAT_RAG_MODEL`은 기존 모드 모델이며 새 모드에서 모델 이름 대체값으로도 읽는다. `LF_CHAT_DATABASE_URL`(실제 DB, 인증 연결 전엔 닫힘), `TOWER_CHAT_DEMO_DB`(가상 DB, `0`이면 검색 끔)는 유지한다. 비밀 설정 파일을 읽거나 수정할 필요 없이 실행 환경값으로 지정할 수 있다.
- 챗봇 부품(langgraph)은 첫 질문 때 만든다. 설치가 안 돼 있어도 관제탑은 켜지고 챗봇 주소만 503

## 5. 재민 님 서버를 따로 세운다면
- 화면을 관제탑(8100)·Docker 앞문(8080)이 열어 주면 그대로 동작한다(같은 주소)
- 다른 서버에서 화면을 연다면 그 서버가 `/chat/` 과 `/chat-widget/` 을 관제탑으로 넘겨야 한다(nginx `location /chat` → 관제탑). 이때는 변재원과 맞춘다

- 복수 색상·미지원 색조·색상 부정을 구분해 안내한다. 현재 검색은 한 가지 표준 색상만 사용하며, 대표 색상 확인 없이 임의 변환하거나 조건을 없애 조회하지 않는다. 여러 품목은 하나씩 선택해 검색한다.

- 11/6 프로젝트 연동 보완: 관제탑·설명 입력·독립 위젯의 모델 생성은 `agents/chat_factory.py`로 통일했다. 잘못된 엔진 이름은 오류로 알린다. 입력 화면 `/health`에서도 `chat_engine`, `chat_model`을 확인할 수 있다.
- 가상 조회 고지·후보 미확정 표시는 서버가 보장한다. 미지원 색조를 복수 색상으로 바꿔 설명한 모델 답변은 서버 안내로 대체한다. 설명 입력/정리만으로 검색이 실행된다는 잘못된 안내는 승인 사용 문서로 대체할 수 있다(`workflow_document_fallback`).
- 연동 범위·검증 결과·제외된 실제 시스템 시험은 `docs/reports/2026-11-06-model-project-integration.md` 참고.
