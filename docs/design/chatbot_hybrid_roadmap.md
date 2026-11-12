# 혼합 구조 적용 순서 (2026-11-10, LF-5)

기준: 팀 확정 구조. 모든 에이전트는 모델+Langfuse 프롬프트, 실제 업무는 코드 도구.
팀 최신 main fd8d1cb에서 별도 작업. 이전 Qwen 스냅샷을 덮어씌우지 않는다.

11/10 실제 모델 후속: 감독 출력 후보를 객체 조합 단위로 제한했다.
같은 입력24건 수락16→24, 기본20문항 감독 수락24/62→62/62.
이는 출력 계약 준수 개선이다. 이후 안내 오류의 검색 경계·핵심 절차 누락·문서 미확인 처리를 보완했다.
실제 기존실패5/5·기본20/20, 추가10개는실행9/10·같은답변표현검토10/10.
실제500전체재측정은 498/500으로 완료했다. staging 라벨 격리·실제 사용 버전/모델 기록도 구현했다.
이번 시험은 로컬 코드 프롬프트 사용이며, 실제 클라우드 검증·production 전환은 사용자 요청으로 보류한다.
마감 보고: `docs/reports/2026-11-10-prompt-provenance-validation.md`.
검증: `docs/reports/2026-11-10-supervisor-constrained-output.md`.
안내 후속: `docs/reports/2026-11-10-guidance-quality.md`.

## 우선순위

1. supervisor 모델 제안 → 코드 검사 → 실행/거절 기록. 실제 호출 횟수 제한.
2. Langfuse staging 라벨 선택·프롬프트 버전/모델 기록·평가 후 production 전환.
3. 접수 초안 버전과 확인 연결, 재시작 복구, 영속적 중복 방지, 실제 인증/동의·접수 adapter.
4. planner 구조화 출력과 나머지 역할/ops 6개 팀의 모델·도구 경계 정비.
5. 실제 Mi:dm 500문항/고정 50 trace, 신규 대화·장애·보안·통합 화면 검증.

시험은 각 단계마다 수행한다. 5순위는 종합 승인 단계이며 시험을 마지막까지 미룬다는 뜻이 아니다.

## 1순위 구현 범위

- `agents/chat_supervisor.py`: action/step/agent 엄격 계약. 행동은 run_step/ask_user/add_step/replan/finish.
- 서버 정책이 허용 후보를 작성하고 모델이 그 안에서 판단한다. 독립적인 검색·안내의 순서 선택 가능.
- 현재 단계 추가/재계획의 범위는 기존 `_judge` 정책이 승인한 작업이다. 모델이 새 작업 문장·SQL·저장 인자를 만들지 않는다.
- 코드 검사기가 형식/후보/업무 경로/권한/사용자 대기/종료 조건/호출 상한을 적용한다.
- 모델이 완료되지 않은 필수 업무를 건너뛰고 reporter로 가던 경로 차단.
- intake 실행 허가는 접수 수집/진행 허가이며 저장 확인을 대신하지 않는다. 저장은 기존 업무 엔진의 책임이다.
- 접수 확인 버튼과 초안 버전의 결합·영속 저장은 3순위에 남아 있다.
- 결과 종류 수 대신 실제 업무 일꾼 dispatch 횟수 사용. 한 질문당 최대 6회(reporter 제외).
- trace `proposal_check`: 모델 제안/accepted 또는 rejected/기계 판독 이유/실제 선택/source.
- 생성 하위 trace도 감독의 임의 필드·임의 문자열을 제거한다. raw 개인정보는 기록하지 않는다.
- API는 supervisor_checks/worker_executions를 추가하고 기존 answer/decisions/plan_steps는 유지한다.

## 활성화·되돌리기

현재 작업은 로컬 구현·가상 검증이다. 실행 중인 팀 서버·Langfuse production은 변경하지 않는다.
supervisor 모델 호출 기본값은 기존처럼 꺼진 상태이며 `LF_AGENT_SUPERVISOR_USE_LLM=1` 또는
해당 Langfuse 프롬프트 config로 켠다. 다른 역할은 이번에 일괄 활성화하지 않는다.

기존 Langfuse supervisor 프롬프트는 choice 형식이다. 새 action/step/agent 프롬프트를
staging에서 평가한 뒤 코드와 함께 전환해야 한다. 기존 production 글을 강제 덮어쓰지 않는다.
구버전 출력·모델 장애는 코드 후보로 대체하며 거절 원인이 남는다.
2순위 staging 로더 구현과 실제 SDK 로컬 모의 API 검증은 완료했다.
실제 클라우드 연결 전까지는 로컬 코드 기본 프롬프트 사용 여부를 명시하여 검증한다.

## 검증 방법

`python -m unittest discover -s tests -p test_chat_supervisor.py`

`python -m unittest discover -s tests -p test_agent_prompts.py`

`python -m unittest discover -s tests`

Windows 시험 프로세스는 PYTHONUTF8=1 권장(키보드 시험의 Node 하위 출력 디코딩).

`python tools/check_chat_supervisor.py --out docs/reports/2026-11-10-supervisor-check.json`

위 도구는 .env/실제 DB/LLM/Langfuse/엑셀을 사용하지 않는다. 500문항을 규칙·첫 후보·마지막 후보·악성 제안
네 방식으로 실행한다. 대역 결과는 실제 Mi:dm 성능 점수와 구분해 별도 JSON에 보존한다.
기존 500문항과 공식 runs/엑셀 점수는 덮어쓰지 않는다.

## 11/11 후속: Planner 지시 계약

최신 팀 main `b1c8979`를 로컬 기능 브랜치에 통합한 뒤 planner의 읽기 작업·입력 참조 v2 계약을 별도 작업했다.
허용 조합, 필수 업무 보존, 구버전 제한 변환, 실제 일꾼 입력 연결은 `planner_instruction_contract.md`에 정리했다.
기존 영속 작업·실제 인증 연결의 운영 적용은 그대로 남아 있으며, 이 planner 변경이 이를 대신하지 않는다.
실제 모델 평가는 통합 버전과 planner 버전을 구분해서 보존한다.
