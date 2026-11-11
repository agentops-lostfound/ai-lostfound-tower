# evaluation — 평가·자동 테스트 (LF-15)

| 파일 | 하는 일 |
| --- | --- |
| `scoring.py` | 고정 채점기: 비전 35C+30P+20R+15A, 검색·로봇·메인 AI 점수, 안전 위반 0점, 개선안 채택 조건 |
| `test_cases.json` | 전 과정 시험 사례 10개(MVP 지갑, 기대 결과는 사람이 정함) |
| `run_cases.py` | 사례 10개 실행 → 점수판(#📈평가-점수 형식) |
| `answer_key_template.csv` | 정답지 예시(지갑 2개 × 5장). 엑셀에서 열어 같은 칸으로 작성 → "CSV UTF-8"로 저장 |
| `answer_key.py` | 정답지 검사: 파일 이름 규칙·값 목록·가시성·세션 누수·검증용/최종 묶음 완비 |
| `improve_loop.py` | AI 자기 개선 회차: 개선용 오차 → 개선안 2개(변경 하나씩) → 검증용으로 채택 판정 → #📈평가-점수 기록 → 멈춤 조건. 지금은 `--demo`(가짜 비전) |
| `eval_vision.py` | 비전 결과(JSON) + 정답지 → 묶음별 비전 점수와 틀린 사진 목록. '최종'은 `--final` 필요 |

```
python evaluation/run_cases.py          # 화면 출력
python evaluation/run_cases.py --send   # 디스코드 전송(.env 웹후크)
python evaluation/answer_key.py evaluation/answer_key_template.csv
python evaluation/improve_loop.py --demo --p95-limit 3        # 연습용 정답지 70장 + 가짜 비전
python evaluation/eval_vision.py --key 정답지.csv --preds 비전결과.json --split 개선용
```
- 정답지·배점·채점 코드·데이터 분할은 개선 에이전트가 바꿀 수 없다(PR 확인을 거쳐 사람만 수정)
- 배점·기준값은 모두 (추정). 첫 측정 뒤 팀이 조정한다

## 챗봇 질문 500개 채점표 (11/9 LF-5)

한줄 설명: 같은 질문 500개를 챗봇 전체 경로(가상 관제탑 + 실제 모델)에 넣어 문항마다 0/1 로 채점하고, 실행할 때마다 엑셀에 **단계 열**(`11/9 01`, `11/9 02` …)을 하나씩 늘려 무엇이 좋아지고(0→1) 나빠졌는지(1→0) 본다.

| 파일 | 하는 일 |
| --- | --- |
| `chat_eval_500.json` | 문항 500개. 수준 6가지: 1 기본 안내 150 · 2 물건 검색 70 · 3 이어 묻기·복합 70 · **4 임무 수행 130**(챗봇이 대화로 분실 접수·습득 신고를 끝까지, 끼어들기·정정·취소·중복 방지·대기 번호 자동 연결) · 5 안전·예외 50 · 6 직원 관제 30. `lf: true` 50문항은 Langfuse 로 보내는 고정 묶음 |
| `chat_eval.py` | 실행기. 문항마다 **새 가상 관제탑**을 메모리에 만들어(앞 문항의 접수가 섞이지 않게) `/chat/questions` 로 대화. 여러 턴이면 모든 턴이 통과해야 1점 |
| `chat_eval_scores.xlsx` | 결과 보기(매번 다시 만들어짐): 점수(단계 열 누적, 합계·통과율 수식, 0→1 초록·1→0 빨강) · 분류별 · 단계 정보(커밋·모델·프롬프트·메모) · 실패 이유(최근) · 사람 판정 |
| `runs/*.json` | 원본 기록(영구 보관 — Langfuse 무료 요금제는 지난 30일만 보임) |
| `chat_eval_overrides.csv` | 사람 판정(자동 채점이 틀렸을 때). 엑셀 '사람 판정' 시트에 적고 저장하면 다음 실행 때 이 파일로 옮겨지고 자동 채점보다 우선 |
| `chat_eval_build.py` | 처음 500개를 만든 스크립트(기록용). 몇 개만 고칠 때는 JSON 을 직접 고친다 |

```
python evaluation/chat_eval.py --model midm-2.0-mini --note "planner 프롬프트 v3"   # 500개 전체 → 단계 기록 + 엑셀
python evaluation/chat_eval.py --rules                       # 모델 없이 규칙만(30초 안팎, 구조 확인용)
python evaluation/chat_eval.py --group 임무 --model midm-2.0-mini   # 일부만(엑셀 기록 안 함, 기록하려면 --record)
python evaluation/chat_eval.py --trace --lf --model midm-2.0-mini   # Langfuse 고정 50문항만 기록 켬
python evaluation/chat_eval.py --excel-only                  # 실행 없이 엑셀만 다시
```
- Langfuse 는 기본으로 **끔**(월 5만 단위 한도: 질문 1개 ≈ 17칸 → 500개 전체를 보내면 한 번에 약 8,500 단위). 자세히 볼 때만 `--trace --lf`
- 프롬프트를 Langfuse 에서 고칠 때: `staging` 라벨로 이 채점표를 먼저 돌리고, 점수가 떨어지지 않을 때만 `production` 으로 옮긴다
- 채점 기준은 문서(docs/guidance/knowledge.json)와 가상 관제탑 기본 물건(흰 모형폰·파란 모형폰·흰 보조배터리 2·빨간 립밤 — 11/11 카드지갑 문항을 립밤 문항으로 바꿈) 기준. 지금 챗봇이 못 하는 것(예: 후보 0개일 때 접수 버튼 제안)도 **목표로** 넣었으므로 처음부터 100점이 아니다
- 걸리는 시간(추정): 규칙만 약 30초 · Mi:dm(그래픽카드) 500문항 약 1~1.5시간 · 클라우드 CPU 는 훨씬 느림
