# LF-5 supervisor 출력 계약 보완·실제 모델 비교

## 결과

이전 실제500문항에서 supervisor 제안3125건 중2002건이 허용 후보 밖이라 코드로 대체됐다.
현재 허용된 후보 객체 전체를 출력 스키마의 enum으로 제한하고 프롬프트를 보완했다.
이는 출력 계약 준수의 개선이며 모델의 의미 판단이 더 정확해졌다는 증거와는 구분한다.

## 바꾼 것

- `chat_supervisor.output_schema`: action/step/agent 각각뿐 아니라 세 값의 조합도 현재 허용 후보로 고정.
  예: (검색,1)/(안내,2)에서 (검색,2)를 만들 수 없게 한다.
- 종료/사용자 대기의 step=0과 빈 agent 유지. 후보 한 개면 그대로 복사하도록 프롬프트 명시.
- 서버 후보를 context의 같은 이름 필드로 덮어쓸 수 없게 입력 조립 순서 수정.
- 빈 후보·잘못된 서버 후보는 스키마 생성 시 실패 처리.
- 기존 `validate`/권한/필수 단계/저장 확인/호출 상한은 완화하거나 우회하지 않았다.
- JSON 필드 이름(action/step/agent), Langfuse 프롬프트 이름, 역할별 모델 설정을 유지.

Ollama의 JSON Schema 출력 제한을 사용한다. root enum의 객체 후보 지원은 설치된 실제 Ollama+Mi:dm으로 확인했다.
[Ollama 공식 설명](https://ollama.com/blog/structured-outputs),
[기반 변환기의 enum/const 처리](https://github.com/ggml-org/llama.cpp/blob/master/common/json-schema.cpp).

## 실제 Mi:dm 비교

| 시험 | 이전 | 수정 후 |
|---|---:|---:|
| 같은 감독 입력24건(12종×2회) | 수락16/24 | **24/24** |
| 같은 기본 대화20문항 | 답변20/20 | **20/20** |
| 기본20문항의 감독 제안 | 수락24/62 | **62/62** |

직접 비교에는 문서·검색·종료·사용자 대기·단계 추가·재계획·직원 분석·접수·복수 후보·지시문이 섞인 데이터를 포함했다.
기존 방식은3849a7f의 프롬프트와 당시 넓은 스키마를 재현했고, 동일 모델·입력으로 비교했다.
현재 프롬프트 해시는 비교 JSON에, 소스 해시는 실패5문항 재검증 JSON의 meta.source_sha256에 보존했다.
기본20문항의 최초 측정 meta.commit은 수정 전 HEAD를 가리킨다. 변경된 작업 파일로 측정한 것이며 전체500 전후 비교로 해석하지 않는다.

## 안전·회귀 검증

- 감독 시험16개 통과(조합 고정/0·빈 값 유지/빈 후보 차단/후보 덮어쓰기 방지4개 추가).
- 모델 대역이 잘못된 JSON/금지 업무를 내면 출력 스키마와 무관하게 최종 코드 검사가 계속 거절한다.
- 전체 unittest1317개 실행,18개 skip,실패0(UTF-8 환경).
- 기존 실패31/68/105/138/146은 실제 Mi:dm으로5개 모두 재현(자동0/5).
  해당 재검증의 감독 제안은16/16 수락. 감독 출력 오류와 기존 안내 오류가 별개임을 확인했다.
- 수정 후 전체500문항은 재실행하지 않았다. 이전495/500을 이번 수정 후 점수로 주장하지 않는다.
- 이번 집중 시험은 Langfuse 끔/코드 기본 프롬프트/가상 데이터 기준이다. 다른 규칙 역할을 일괄 모델 활성화하지 않았다.

## 남은 일

1. 31번: 신분증 안내에 불필요한 검색을 붙이는 planner 경로 보완.
2. 105/146번: 질문에 필요한 답을 빠뜨리거나 다른 절차로 답하는 researcher 적합성 보완.
3. 68/138번: 어색한 표현·절차 설명 충실도와 채점 기준의 표현 차이 함께 검토.
4. staging 라벨 선택·프롬프트 버전 기록 연결 후 실제500문항과 신규 대화로 종합 승인.

팀 서버/.env/Langfuse production/GitHub/Jira는 변경하지 않았다. 로컬 브랜치에서만 작업했다.

## 증거·재현

- `tools/check_supervisor_contract.py --out docs/reports/2026-11-10-supervisor-contract-comparison.json`
- `tools/validate_chat_midm.py --suite live --out docs/reports/2026-11-10-midm-live-constrained.json`
- `tools/validate_chat_midm.py --suite 500 --only 31,68,105,138,146 --out docs/reports/2026-11-10-midm-failures-constrained.json`
- 전체 회귀: `python -m unittest discover -s tests`

검증 도구는 .env/팀 DB/Langfuse/기존 엑셀을 읽거나 변경하지 않는다. 원본 비교 기록은 덮어쓰지 않았다.
