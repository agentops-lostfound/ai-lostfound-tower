# 정연우 작업 완료 · 변재원 이어받기 (11/5)

한줄 설명: 11/5 역할 조정으로 챗봇은 변재원이 맡는다. 정연우가 지금까지 한 LF-5(챗봇)·LF-9(회수·통계) 작업은 **완료**로 보고 main 에 모두 넣었으며, 이후 이어지는 작업은 변재원이 한다.

## 1. 완료로 넣은 정연우 작업
| PR | 내용 | main 반영 |
| --- | --- | --- |
| #61 | 웹 안내 챗봇(문서 근거 RAG · LangGraph 안내/물건 검색 분기 · 음성 입력 · `web/lost-input/`) | #71 (11/5) |
| #76 | 설명 → 특징 매칭 내부 검사(`agents/matching_inspection.py`, `tools/check_chat_matching.py`), #73 안내 주제와 맞추기, 챗봇 오류 문구에서 내부 오류 내용 숨기기 | 이 PR |
| #64 | LF-9 회수·도착·장소·접수 통계 독립 시연(`web/collection-desk/`, `agents/center_demo.py`, `center/demo_*`), 기록 일관성 점검 | 이 PR |
- 커밋은 작성자 이름(정연우) 그대로 합쳤다. 원본 PR 은 GitHub 가 병합됨으로 표시한다

## 2. 그대로 지키는 정연우 원칙
- 챗봇의 실제 팀 DB 검색은 서버가 본인인증 세션을 검증할 때만 열린다(`SearchAgent(authorize=...)` — 검증기는 김재민 관제탑 쪽)
- 미정 운영값(운영시간·보관기간·주소)은 지어내지 않고 "확정 안 됨"
- 오류 응답에 모델·DB 내부 오류 문구를 내보내지 않는다(#76)

## 3. 회수·통계 시연(LF-9)의 위치
- 독립 시연이다: `python -m tools.run_collection_demo` → `http://127.0.0.1:8110/collection-desk`, 저장은 `.cache/center-collection-demo.sqlite3`(가상 물건 6개). 관제탑(8100)·팀 DB 와 연결돼 있지 않다
- 직원(관리자)용 화면이라 11/5 결정(직원 단계 제외)과 겹친다 → **관제탑 관리자 화면으로 쓸지, 참고로만 둘지는 김재민(관제탑·화면) 구조 정리 때 결정**
- 회수 알림용 DB 변경은 자동 적용하지 않는 `center/migrations/pending/` 에 있다(DB 담당 검토 후 적용)

## 4. 11/5 함께 고친 것(변재원)
- 관리자 로그인(김재민 `agents/admin_auth.py`, 진행 중)이 켜지면 `/live/state`·`/returns`·`/robot/home` 이 잠긴다 → 분실물봇(`tools/lostfound_bot.py`)과 관제 분석 에이전트(`agents/ops_analyst.py`)가 `.env` `LF_ADMIN_API_KEY` 를 `X-Admin-Key` 헤더로 보내게 했다. 키가 없는데 잠겨 있으면 봇이 "LF_ADMIN_API_KEY 를 넣고 다시 켜 주세요"라고 알린다
- 시험: `tests/test_admin_key_clients.py`

## 5. 이어서 할 일(변재원)
1. 실제 마이크로 한국어 음성 입력 확인(정연우 문서에 미검증으로 남음)
2. 챗봇 평가 질문 늘리기 + 조작 질문(레드팀) 시험
3. 본인인증 검증기 연결 약속(김재민) → 챗봇 실제 DB 검색
4. 분실인 웹 완성 뒤 챗봇 위젯 붙이기(`web/chat-widget/README.md`)
