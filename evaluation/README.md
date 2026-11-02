# evaluation — 평가·자동 테스트 (LF-15)

| 파일 | 하는 일 |
| --- | --- |
| `scoring.py` | 고정 채점기: 비전 35C+30P+20R+15A, 검색·로봇·메인 AI 점수, 안전 위반 0점, 개선안 채택 조건 |
| `test_cases.json` | 전 과정 시험 사례 10개(MVP 지갑, 기대 결과는 사람이 정함) |
| `run_cases.py` | 사례 10개 실행 → 점수판(#📈평가-점수 형식) |
| `answer_key_template.csv` | 정답지 예시(지갑 2개 × 5장). 엑셀에서 열어 같은 칸으로 작성 → "CSV UTF-8"로 저장 |
| `answer_key.py` | 정답지 검사: 파일 이름 규칙·값 목록·가시성·세션 누수·검증용/최종 묶음 완비 |
| `eval_vision.py` | 비전 결과(JSON) + 정답지 → 묶음별 비전 점수와 틀린 사진 목록. '최종'은 `--final` 필요 |

```
python evaluation/run_cases.py          # 화면 출력
python evaluation/run_cases.py --send   # 디스코드 전송(.env 웹후크)
python evaluation/answer_key.py evaluation/answer_key_template.csv
python evaluation/eval_vision.py --key 정답지.csv --preds 비전결과.json --split 개선용
```
- 정답지·배점·채점 코드·데이터 분할은 개선 에이전트가 바꿀 수 없다(PR 확인을 거쳐 사람만 수정)
- 배점·기준값은 모두 (추정). 첫 측정 뒤 팀이 조정한다
