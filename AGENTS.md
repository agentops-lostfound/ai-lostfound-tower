# AGENTS.md — ai-lostfound-tower (AgentOps 팀 저장소)

OpenAI Codex 같은 AI 코딩 도구가 이 저장소에서 작업할 때 따르는 규칙이다.
Claude Code 는 `CLAUDE.md` 를 읽고, Codex 는 이 파일을 읽는다. 두 파일의 규칙은 같게 유지한다(한쪽을 바꾸면 다른 쪽도 바꾼다).

## 프로젝트
- AI 분실물 관제탑: 습득물 등록기계 → 본센터(공용 보관함 + 탑뷰 카메라 + SO-101 로봇팔) → 분실인 웹, 이를 관제하는 AI 관제탑
- MVP: 지갑 1종 → 성공하면 USB·립밤·모형폰. 업무는 Jira LF-1~21(스페이스 키 LF)
- 설계 문서: `docs/design/` (구조도 `architecture.md`, DB `database.md`)
- 기준 입·출력 약속: `agents/contracts.py`, `docs/contracts/mcp_tools.md` — 바꾸면 PR 본문에 이유를 적고 "변재원 확인 필요"라고 쓴다

## 폴더와 담당
| 폴더 | 내용 |
|---|---|
| `agents/` | AI 관제탑(흐름·API·DB 부품·MCP) |
| `center/` | 팀 DB 표 설계(`schema.sql`)와 시연 데이터 |
| `vision/` | 비전(탑뷰 카메라·품목 인식) |
| `intake_machine/` | 습득물 등록기계 화면 |
| `web/` | 분실인 웹 |
| `robot/` | SO-101 로봇팔 |
| `evaluation/` | 시험 사례·채점 |
| `discord_ops/` | 디스코드 관제 알림 |
- 자기 업무 폴더 밖의 파일을 고쳐야 하면 PR 본문에 어떤 파일을 왜 고쳤는지 적는다

## 작업 방식
- 한국어로 답하고, PR 제목·본문·커밋 메시지도 한국어로 쓴다. 코드·명령어·파일명·오류 원문은 그대로 둔다
- 업무 하나 = 브랜치 하나: `LF-번호-이름-영문-설명` (예: `LF-8-yeonwoo-db-review`, 이름은 요청한 팀원의 영문 이름). `codex/...` 같은 자동 이름은 쓰지 않는다
- 커밋 메시지: `LF-번호 무엇을 왜 (한국어)`
- `main` 에 직접 push 하지 않는다(보호 규칙으로 막혀 있음). 항상 PR 로 올린다
- force push, `git reset --hard` 후 push 처럼 기록을 지우는 명령은 쓰지 않는다
- 폴더와 파일 이름은 영문으로 쓴다

## 비밀값·개인정보
- `.env`(웹후크 주소, 토큰, API 키, DB 비밀번호)는 읽거나 출력하거나 커밋하지 않는다. 필요한 값의 이름만 `.env.example` 에 적는다
- 실제 개인정보, 신분증 사진, 물건 사진 원본, 모델 가중치, 5MB 넘는 파일은 올리지 않는다
- 디스코드·로그 메시지에는 개인정보 없이 물건 번호·사례 번호만 쓴다

## 개발 환경 설정 (Codex 클라우드 환경의 setup script 에 그대로 쓸 수 있음)
```bash
python -m pip install --upgrade pip
pip install -r agents/requirements.txt
```
- 파이썬 3.11 이상
- 비전 학습(`vision/requirements.txt`)은 용량이 커서 클라우드 환경에는 설치하지 않는다
- 시험은 DB·디스코드·Ollama 없이도 돈다. 실제 DB 시험은 `LF_TEST_DSN` 환경값이 있을 때만 실행된다

## 바꾼 뒤 반드시 할 것
```bash
python -m unittest discover -s tests
```
- 모두 통과해야 PR 을 올린다. PR 에서도 GitHub Actions 가 같은 시험을 자동으로 돌리고, 통과 + 팀원 1명 승인이 있어야 병합된다. 실패하면 고치거나, 고치지 못한 이유를 PR 본문에 적는다
- PR 본문 형식: Jira 번호 / 무엇을 / 왜 / 시험 결과

## 자주 쓰는 명령 (저장소 폴더, .venv 켠 상태)
- 관제탑 시연 요약: `python tools/tower_demo.py`
- 시험 사례 10개: `python evaluation/run_cases.py`
- 자기 개선 회차 연습: `python evaluation/improve_loop.py --demo --p95-limit 3`
- 환경 점검: `python tools/check_ai_env.py`
