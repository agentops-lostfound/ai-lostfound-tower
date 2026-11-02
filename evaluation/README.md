# evaluation — 평가·자동 테스트 (LF-15)

| 파일 | 하는 일 |
| --- | --- |
| `scoring.py` | 고정 채점기: 비전 35C+30P+20R+15A, 검색·로봇·메인 AI 점수, 안전 위반 0점, 개선안 채택 조건 |
| `test_cases.json` | 전 과정 시험 사례 10개(MVP 지갑, 기대 결과는 사람이 정함) |
| `run_cases.py` | 사례 10개 실행 → 점수판(#📈평가-점수 형식) |

```
python evaluation/run_cases.py          # 화면 출력
python evaluation/run_cases.py --send   # 디스코드 전송(.env 웹후크)
```
- 정답지·배점·채점 코드·데이터 분할은 개선 에이전트가 바꿀 수 없다(PR 확인을 거쳐 사람만 수정)
- 배점·기준값은 모두 (추정). 첫 측정 뒤 팀이 조정한다
