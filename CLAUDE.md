# CLAUDE.md — ai-lostfound-tower (AgentOps 팀 저장소)

이 저장소에서 Claude Code로 작업할 때(팀원 PC의 개발 세션, 디스코드 2조 봇 세션 모두) 따르는 규칙이다.
Codex 는 같은 내용의 `AGENTS.md` 를 읽는다. 규칙을 바꾸면 두 파일을 함께 바꾼다.

## 프로젝트
- AI 분실물 관제탑: 습득물 등록기계 → 본센터(공용 보관함 + 탑뷰 카메라 + SO-101 로봇팔) → 분실인 웹, 이를 관제하는 AI 관제탑
- MVP: 지갑 1종 → 성공하면 USB·립밤·모형폰·핸드크림·보조배터리(품목 6종, agents/contracts.py CATEGORIES). 업무는 Jira 스페이스 LF — 에픽 LF-1(접수·찾기)·LF-7(센터·데이터)·LF-13(관제탑) 아래 작업(11/4 기준 LF-34까지, 번호는 에픽별 1.x·2.x·3.x 를 이어서)
- 기준 입·출력 약속: `agents/contracts.py`, `docs/contracts/mcp_tools.md` — 바꾸면 PR에 이유를 적고 팀원 확인
- 11/6 역할: 화면·관제탑(API·DB·로봇 연결)·챗봇 변재원(11/5 정연우, 11/6 김재민 작업 완료 후 이어받음) · 비전·매칭·집기 김건태 · 로봇팔 이순필. 관제탑 인수인계 `docs/design/tower_handover.md`, 이어받기 기록 `docs/reports/2026-11-06-jaewon-takeover-jaemin.md`

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
- 챗봇 실제 모델 회귀 시험(사용자 말투 질문 18개, Ollama 켠 상태): `python tools/chat_live_check.py --model midm-2.0-mini` — 모델·프롬프트·검사기를 고치면 돌린다. 안내 docs/design/chatbot_sllm_rag.md §13
- 관제탑 메인 AI(매칭이 애매할 때 매칭·보관 칸·비전 에이전트 협업): `.env` TOWER_BRAIN=1, 가상 시연은 분실 메시지 끝에 `#흐린촬영` → `/live` 의 메인 AI 대화 패널 — 안내 docs/design/tower_main_ai.md
- 에이전트 대화(메인 AI 아래 요청·답·채점·도움·배운 점, 가상 시연은 기본 켜짐·끄기 `TOWER_AGENT_TALK=0`): `/live` 🤖 에이전트 대화 패널 + 디스코드 `DISCORD_WEBHOOK_AGENT`(대화 하나에 한 번) — 안내 docs/design/agent_talk.md
- 가짜 보관함 시나리오 9개(부품 교체 확인용, 디스코드 요약 `--discord`, 매칭 두 방식 비교 `--compare`): `python tools/mock_scene.py` — 안내 docs/design/swap_guide.md
- 키오스크 사진 → Qwen 특징 작업자(관제탑과 같은 PC, Qwen 전용 가상환경): `.\.venv-qwen\Scripts\python.exe tools\intake_qwen_worker.py` (연결만 확인 `--check`) — 안내 docs/design/virtual_demo.md §4-5
- 자기 개선 회차 연습: `python evaluation/improve_loop.py --demo --p95-limit 3`
- 정답지 검사: `python evaluation/answer_key.py 정답지.csv`
- 시연 물건 상태 되돌리기: `python tools/reset_demo.py` (미리보기) → `--apply`
- 관제탑 켜기: `tools\start_tower.bat`(팀 DB·화면 앞문 Docker 도 함께, 교육원 네트워크 공개는 `lan`, 코드가 바뀌면 스스로 다시 켜지는 개발 모드는 `dev`). Docker 는 `docker-compose.yml` 하나뿐(db 5434 · web 8080) · 화면 지도 `web/README.md` · 로봇 계약 `docs/contracts/robot_api.md`
- 전체 가상 시연(디스코드 분실물 채널 → 습득·찾기·반환): `.env` TOWER_SIM=1 로 관제탑 → `python tools/lostfound_bot.py` (디스코드 없이 `--try "메시지"`), 화면 `/live` — 안내 docs/design/virtual_demo.md
