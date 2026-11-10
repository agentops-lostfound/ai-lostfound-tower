# CLAUDE.md — ai-lostfound-tower (AgentOps 팀 저장소)

이 저장소에서 Claude Code로 작업할 때(팀원 PC의 개발 세션, 디스코드 2조 봇 세션 모두) 따르는 규칙이다.
Codex 는 같은 내용의 `AGENTS.md` 를 읽는다. 규칙을 바꾸면 두 파일을 함께 바꾼다.

## 프로젝트
- AI 분실물 관제탑: 습득물 등록기계 → 본센터(공용 보관함 + 탑뷰 카메라 + SO-101 로봇팔) → 분실인 웹, 이를 관제하는 AI 관제탑
- 품목: 11/9 4종 고정 — 목업폰(모형폰)·보조배터리·핸드크림·카드지갑(지갑). 립밤(YOLO 인식 어려움)·USB 는 운영에서 뺌 → 운영 품목은 agents/contracts.py ACTIVE_CATEGORIES 한 곳에서만 정함(계약 CATEGORIES 에는 옛 기록용으로 남김). 보관함 열: R1 휴대폰('/' 45도) · R2 카드지갑 · R3 보조배터리 · R4 핸드크림. 업무는 Jira 스페이스 LF — 에픽 LF-1(접수·찾기)·LF-7(센터·데이터)·LF-13(관제탑) 아래 작업(11/4 기준 LF-34까지, 번호는 에픽별 1.x·2.x·3.x 를 이어서)
- 기준 입·출력 약속: `agents/contracts.py`, `docs/contracts/mcp_tools.md` — 바꾸면 PR에 이유를 적고 팀원 확인
- 11/9 역할: 화면·관제탑(API·DB·로봇 연결) 변재원(11/6 김재민 작업 이어받음) · 챗봇 변재원(11/9 대화 접수·혼합 구조·500문항 채점표까지) → 정연우가 이어서 개발하고 화면을 사람 눈으로 검토 · 비전·매칭·집기 김건태 · 로봇팔 이순필. 관제탑 인수인계 `docs/design/tower_handover.md`, 이어받기 기록 `docs/reports/2026-11-06-jaewon-takeover-jaemin.md`, 챗봇 인수인계 `docs/reports/2026-11-09-chatbot-handoff-jaewon-to-yeonwoo.md`
- 11/9 챗봇 구조 결정: **혼합 구조** — 에이전트(coordinator·planner·supervisor·researcher·item_search·intake·reporter)마다 모델 + 프롬프트(Langfuse 버전 관리), 검색·접수·숫자는 코드 도구, 모델은 규칙이 허용한 목록 안에서만 고름. 결정 기록 `docs/design/chatbot_agents.md` 0장

## 답변·작업 방식
- 한국어로 답한다. 코드·명령어·파일명·오류 원문은 그대로 둔다
- 결론 먼저, 입문자 기준 설명. 확실하지 않으면 추측이라고 밝힌다
- 코드를 바꾸면 `python -m unittest discover -s tests` 를 실행해 통과를 확인한 뒤 보고한다
- 업무 하나 = 브랜치 하나(`LF-번호-이름-영문-설명`, 이름은 요청한 팀원의 영문 이름), 커밋 메시지는 `LF-번호 무엇을 왜 (한국어)`. main 에 직접 push 하지 않는다
- force push 처럼 기록을 지우는 명령은 쓰지 않는다

## 비밀값
- `.env`(웹후크 주소, 토큰, API 키)는 읽거나 출력하거나 커밋하지 않는다. 필요한 값의 이름만 `.env.example` 에 적는다
- 디스코드·로그 메시지에는 개인정보 없이 물건 번호·사례 번호만 쓴다

## 자주 쓰는 명령 (저장소 폴더, .venv 켠 상태)
- 전체 시험: `python -m unittest discover -s tests`
- 관제탑 시연 요약: `python tools/tower_demo.py` (관제 채널 전송은 `--send`, LLM 검토는 `--reviewer`)
- 시험 사례 10개: `python evaluation/run_cases.py`
- 관제 분석·보고 에이전트(LangManus 구조): `python tools/ops_report.py "오늘 반환 실패 원인 알려줘"` (로컬 모델 `--model`, 관제탑 없이 `--from-json`) — 안내 docs/design/ops_analyst.md
- 챗봇 Langfuse 연결(실행 기록·프롬프트): `python tools/langfuse_setup.py --check` → `--push-prompts` → `--test-trace` — 안내 docs/design/chatbot_sllm_rag.md §11
- 챗봇 실제 모델 회귀 시험(사용자 말투 질문 20개, Ollama 켠 상태): `python tools/chat_live_check.py --model midm-2.0-mini` — 모델·프롬프트·검사기를 고치면 돌린다. 안내 docs/design/chatbot_sllm_rag.md §13
- 챗봇 질문 500개 채점표(기본 안내 → 검색 → 이어 묻기 → 대화로 접수 끝까지 → 안전·직원 관제, 문항마다 0/1, 실행할 때마다 엑셀에 단계 열 추가): `python evaluation/chat_eval.py --model midm-2.0-mini` (모델 없이 `--rules`, Langfuse 고정 50문항 `--trace --lf`) → `evaluation/chat_eval_scores.xlsx` · 원본 기록 `evaluation/runs/` — 안내 evaluation/README.md
- 챗봇 에이전트 구조·대화 접수(DeerFlow 모양 coordinator→planner→supervisor⇄일꾼, 11/9 intake 로 분실 접수·습득 신고까지, supervisor 판단은 Langfuse 에 기록): 안내 docs/design/chatbot_agents.md · 시험 `tests/test_chat_intake.py`
- 관제탑 메인 AI(매칭이 애매할 때 매칭·보관 칸·비전 에이전트 협업): `.env` TOWER_BRAIN=1, 가상 시연은 분실 메시지 끝에 `#흐린촬영` → `/live` 의 메인 AI 대화 패널 — 안내 docs/design/tower_main_ai.md
- 에이전트 대화(메인 AI 아래 요청·답·채점·도움·배운 점, 가상 시연은 기본 켜짐·끄기 `TOWER_AGENT_TALK=0`): `/live` 🤖 에이전트 대화 패널 + 디스코드 `DISCORD_WEBHOOK_AGENT`(대화 하나에 한 번) — 안내 docs/design/agent_talk.md
- 가짜 보관함 시나리오 9개(부품 교체 확인용, 디스코드 요약 `--discord`, 매칭 두 방식 비교 `--compare`): `python tools/mock_scene.py` — 안내 docs/design/swap_guide.md
- 키오스크 사진 → Qwen 특징 작업자(관제탑과 같은 PC, Qwen 전용 가상환경): `.\.venv-qwen\Scripts\python.exe tools\intake_qwen_worker.py` (연결만 확인 `--check`, 환경이 없는 PC 는 먼저 `tools\setup_qwen.bat`) — 안내 docs/design/virtual_demo.md §4-5
- 자기 개선 회차 연습: `python evaluation/improve_loop.py --demo --p95-limit 3`
- 정답지 검사: `python evaluation/answer_key.py 정답지.csv`
- 시연 물건 상태 되돌리기: `python tools/reset_demo.py` (미리보기) → `--apply`
- 로봇팔 ↔ DB 연결(탑뷰 없이 칸 번호 1~8 = pose_1~8, 가까운 줄 1·3·5·7 · 먼 줄 2·4·6·8): `.env` TOWER_ROBOT_TARGET=db · TOWER_ROBOT_PART=모듈:클래스, 읽기 `GET /api/admin/storage/robot-target/{물건번호}` — 안내 docs/contracts/robot_db_target.md
- 키오스크 서버 카메라(태블릿은 화면만, 웹캠은 관제탑 PC): 번호 찾기 `python tools/list_cameras.py`(관제탑을 끈 상태에서, "영상이 보이는 번호") → `.env` TOWER_KIOSK_CAMERAS=KIOSK-A=번호(교육원 PC 웹캠 1대 = 0, 11/9 확인) → 태블릿 `/kiosk?machine=KIOSK-A&cam=server` — 안내 web/README.md 키오스크 카메라 설정
- 관제탑 켜기: `tools\start_tower.bat`(팀 DB·화면 앞문 Docker 도 함께, 교육원 네트워크 공개는 `lan`, 코드가 바뀌면 스스로 다시 켜지는 개발 모드는 `dev`). Docker 는 `docker-compose.yml` 하나뿐(db 5434 · web 8080) · 화면 지도 `web/README.md` · 로봇 계약 `docs/contracts/robot_api.md`
- 발표 통합 시연 점검표(켜는 순서 → 화면 배치 → 한 바퀴 흐름 → 막혔을 때 대체, 리허설 기록): docs/design/demo_checklist.md
- 통합 시연 화면(11/10, 발표용 한 화면): `/showcase` — 세로 키오스크·휴대폰 + DB 실시간 기록(agents/db_watch.py) + AI 에이전트 흐름(agents/observability.py 리스너) + Qwen 사진 분석 카드(읽은 값 → 저장한 값, agents/vision_watch.py), 자료는 `/api/admin/live/state?detail=1` — 안내 web/README.md 1-00
- 가상 시연 기록을 팀 DB 에도 함께 저장(11/10, agents/db_mirror.py): `tools\start_tower.bat` 가 기본으로 켬(`TOWER_SIM_DB=1`), 끄기 `start_tower.bat nodb`. 실제 기록은 덮지 않음(가상 물건 `object_id='SIM'`, 칸은 `assigned_by='system'` 만). 확인 `/showcase` [팀 DB 조회] · 진짜 PostgreSQL 시험 `LF_TEST_DATABASE_URL=… python -m unittest tests.test_db_mirror`
- 전체 가상 시연(디스코드 분실물 채널 → 습득·찾기·반환): `.env` TOWER_SIM=1 로 관제탑 → `python tools/lostfound_bot.py` (디스코드 없이 `--try "메시지"`), 화면 `/live` — 안내 docs/design/virtual_demo.md
