# LF-5 영속 작업 계약 대역 검증

2026-11-11 정연우. 로컬 작업이며 GitHub/Jira 게시·main 병합은 하지 않는다.

## 변경과 검증 범위

시작 HEAD `67c1cbb`의 기존 확인 연결·완료 불명 보호는 보존한다.
작업 브랜치는 `LF-5-jeongyeonwoo-intake-operation-contract`이며 원본 브랜치와 커밋을 그대로 남겼다.
새 `agents/chat_operations.py`는 명시 주입형 영속 작업 장부와 서버 내부 창구 계약이다.
`tests/intake_operation_fixture.py`는 업무 효과와 영수증을 같은 SQLite 트랜잭션에 저장하는 독립 대역이다.
운영 창구·실제 DB·인증·위젯에 자동 연결하지 않는다.

| 검증 | 결과 |
|---|---|
| 독립 준비 폴더 집중 시험 | 23개 통과, 2.511초 |
| 원본 저장소 반영 후 전체 Python 시험 | 1589개 검사 / 환경 조건 제외 23개 / 실패 0, 50.100초 |
| 기존 위젯 Node 시험 | 31개 통과 / 실패 0 (VM 기반 시험) |

집중 시험은 임시 파일 DB와 가상 식별자만 사용했다. 코드 기본 프롬프트·모델을 바꾸지 않아 실제 모델 재평가는 하지 않았다.
Langfuse 클라우드·production 검증은 보류 상태를 유지했다.
전체 시험에서도 `LF_TEST_DSN`, `LF_TEST_DATABASE_URL`을 비워 실제 DB 시험을 제외했고
`LF_LANGFUSE=0`, `TOWER_SEND=0`을 적용했다. `.env`는 읽지 않았다.

검증 명령(저장소 루트, 기존 `.venv-support` Python):

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:LF_LANGFUSE='0'
$env:TOWER_SEND='0'
$env:LF_TEST_DSN=''
$env:LF_TEST_DATABASE_URL=''
..\.venv-support\Scripts\python.exe -m unittest discover -s tests
node --test tests/test_chat_widget.cjs tests/test_chat_widget_window.cjs
```

## 확인한 장애·권한 경계

- 최초 업무 저장 전 ID 영속화와 재시작 후 같은 수락 초안 ID 복원.
- found/lost/answer/cancel_claim의 정상 완료·업무 거절·저장 후 응답 유실 복구.
- 스레드 동시 준비/실행, 별도 프로세스 동시 실행, 창구 자체 동일 작업 ID 재전송의 업무 효과 한 번.
- 실제 하위 프로세스를 `os._exit`로 트랜잭션 전/후 종료한 뒤 재조회.
  커밋 전은 업무/영수증 모두 롤백되어 불명 유지, 커밋 후는 원래 ID로 결과 복구.
- 다른 사용자·다른 인증 세션은 장부 조회/실행/복구 모두 차단, 창구 접근도 하지 않음.
- 작업 ID·소유자·업무 종류·요청 해시가 다른 영수증, 잘못된 결과 번호는 복구 증거로 거절.
- 조회 오류·미발견은 불명 유지, 재저장 금지. 늦은 조회 오류가 완료 결과를 지우지 않음.
- 장부에 초안/가린 신분 정보/소유자 원문/확인 값/오류 원문/키를 남기지 않음.

## 최신 팀 변경과 남은 연결

GitHub 읽기 비교 시 기준 main `43d973b` 이후 12개 커밋이 있었고 공통 작업 조회 계약은 여전히 없었다.
팀의 역 변경·로고·화면 보완은 조회만 했으며 이번 시제품에 팀 main을 병합하지 않았다.
이번 전체 시험은 시작 HEAD와 신규 시제품에 대한 검증이며 최신 팀 main 통합 검증이 아니다.

계약 상세와 원격 파일 blob은 `docs/design/intake_operation_contract.md`에 기록했다.
다음 작업은 업무 창구의 원자적 영수증·인증 주체/세션·수락 초안 영속 ID·최소 화면 복구 결과를 담당자와 맞추는 것이다.
그 뒤 기존 확인 검사 다음에 장부를 연결하고, 새 대화/다른 화면에서도 미확정 작업을 복원해야 한다.

**현재 운영 챗봇의 자동 복구·프로세스 재시작 중복 방지가 완성된 것은 아니다.**
이 시제품의 저장 한 번 보장은 같은 작업 ID와 트랜잭션 대역 안의 업무 DB 효과에 한정된다.
새 초안 ID로 다시 보내는 의미상 중복, 실제 인증, 로봇/비동기 후속 작업, 운영자 복구·보관 정책은 남아 있다.
