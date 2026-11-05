# 관제 분석·보고 에이전트 (11/5, 변재원 LF-5)

한줄 설명: "오늘 반환 실패 원인 알려줘"라고 하면 관제탑 기록을 읽어 숫자를 계산하고, 한국어 보고서를 써 주는 멀티에이전트다.

## 1. 구조 — LangManus 에이전트 팀을 LangGraph 로
```
요청 → coordinator(조정자: 관제 분석 요청인가?) ── 아니면 안내 후 끝
          ↓
       planner(계획자: 초점 = 전체·실패·로봇·속도)
          ↓
       supervisor(감독자) ⇄ researcher(조사자: 관제탑 GET /returns, /live/state)
                          ⇄ analyst(분석자: 고정 계산 — 비율·이유 순위·막힌 단계·처리 시간)
                          ⇄ reporter(보고자: 보고서) → 끝
```
| LangManus 원본 | 여기 | 바꾼 이유 |
| --- | --- | --- |
| researcher(Tavily 웹 검색) | 관제탑 기록 읽기(GET 만) | 우리 자료는 웹이 아니라 관제 기록 |
| coder(임의 Python·bash 실행) | analyst(정해진 계산 함수) | 임의 코드 실행은 위험 — 필요한 계산이 정해져 있음 |
| browser | 없음 | 필요 없음 |
| reporter(LLM 자유 작성) | LLM 작성 + **숫자 검증**, 실패 시 템플릿 | 보고서 숫자를 지어내지 못하게 |
| OpenAI 호환 API 키 | 로컬 Ollama(선택) | 키 없이 교육원 PC 에서 |

- LangManus(github.com/Darwin-lfl/langmanus, MIT)는 2025년 이후 관리가 멈춰(추정, 마지막 커밋 약 1년 전) 패키지를 직접 설치하지 않고 구조만 따랐다
- 한줄 설명 — **멀티에이전트**: 역할이 다른 AI 여러 개가 일을 나눠 하는 방식(조정자가 받고, 계획자가 나누고, 담당자가 하고, 보고자가 정리)
- 한줄 설명 — **감독자(supervisor)**: 다음에 누가 일할지 정하는 교통정리 담당. 여기서는 단계 수 8회 제한으로 무한 반복을 막는다

## 2. 실행 (교육원 PC, 저장소 폴더, .venv)
```
python tools/ops_report.py "오늘 반환 실패 원인 알려줘"
python tools/ops_report.py "로봇팔 문제 요약해줘" --model qwen3-vl:2b-instruct
python tools/ops_report.py "전체 현황" --save data/reports/ops.md
python tools/ops_report.py "전체 현황" --from-json 기록.json      # 관제탑 없이
```
- 관제탑(8100)이 켜져 있어야 한다. 가상 시연(TOWER_SIM=1)에서 습득·찾기를 몇 번 돌린 뒤 실행하면 숫자가 나온다
- `.env` `OPS_ANALYST_MODEL`(이름만) — 비우면 LLM 없이 템플릿 보고서
- 관제 분석이 아닌 질문("점심 뭐 먹지?")은 기록을 읽지 않고 안내만 한다

## 3. 안전 규칙
- 읽기만: 관제탑 GET 두 개(`/returns?limit=100`, `/live/state`). 쓰기·로봇 명령 없음
- LLM 에는 계산된 숫자 묶음(facts)만 준다. 보고서에 facts 에 없는 숫자가 하나라도 있으면 그 보고서를 버린다
- 보고서에는 사례 번호·물건 번호 외 개인정보가 없다(기록 자체에 없음)

## 4. 다음
- 디스코드 관제 채널에 하루 요약 자동 전송(사용자 허락 후)
- 챗봇 위젯에서 직원용 "관제 요약" 질문 연결(직원 인증 정해진 뒤)
- 시험: `tests/test_ops_analyst.py`(LLM 숫자 검증·관제탑 꺼짐·주제 밖 질문)
