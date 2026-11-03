# CLAUDE.md — ai-lostfound-tower (AgentOps 팀 저장소)

이 저장소에서 Claude Code로 작업할 때(팀원 PC의 개발 세션, 디스코드 2조 봇 세션 모두) 따르는 규칙이다.
Codex 는 같은 내용의 `AGENTS.md` 를 읽는다. 규칙을 바꾸면 두 파일을 함께 바꾼다.

## 프로젝트
- AI 분실물 관제탑: 습득물 등록기계 → 본센터(공용 보관함 + 탑뷰 카메라 + SO-101 로봇팔) → 분실인 웹, 이를 관제하는 AI 관제탑
- MVP: 지갑 1종 → 성공하면 USB·립밤·모형폰·핸드크림·보조배터리(품목 6종, agents/contracts.py CATEGORIES). 업무는 Jira LF-1~21(스페이스 키 LF)
- 기준 입·출력 약속: `agents/contracts.py`, `docs/contracts/mcp_tools.md` — 바꾸면 PR에 이유를 적고 팀원 확인

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
- 가짜 보관함 시나리오 9개(부품 교체 확인용, 디스코드 요약 `--discord`): `python tools/mock_scene.py` — 안내 docs/design/swap_guide.md
- 자기 개선 회차 연습: `python evaluation/improve_loop.py --demo --p95-limit 3`
- 정답지 검사: `python evaluation/answer_key.py 정답지.csv`
- 시연 물건 상태 되돌리기: `python tools/reset_demo.py` (미리보기) → `--apply`
