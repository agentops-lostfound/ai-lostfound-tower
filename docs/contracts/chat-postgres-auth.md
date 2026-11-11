# LF-5 운영 PostgreSQL·사용자 인증 연결

2026-11-11 정연우. 코드 연결과 대역 검증 완료. 실제 인증 발급 서버/읽기 뷰 연결 및 운영 DB 검증은 미완료다.

## 연결된 경로

- `agents.api.build_app`와 `agents.lost_api.create_app/from_environment`가 같은 사용자 인증 검증기를 받는다.
- `build_chatbot_from_env`가 기존 `SearchAgent.authorize`에 서버 세션 검증기를 연결한다.
- 인증 연결을 명시 설정하면 비직원 `POST /chat/questions`는 유효한 Bearer 세션을 요구한다.
  만료·철회·본인인증 미완료·필수 동의 누락·권한 부족은 401, 인증 DB 장애는 503이다.
- `GET /chat/operations/{operation_id}`는 현재 인증 소유자의 영수증만 읽는다. 권한 검증 없이 DB를 조회하지 않는다.
- 사용자별 대화 상태는 서버 HMAC으로 사용자/인증 세션/화면 대화 번호를 결합한다.
  같은 화면 번호를 알아도 다른 사용자나 다른 인증 세션의 초안·확인 상태에 접근할 수 없다.
- 직원 로그인은 일반 사용자 인증을 대체하지 않는다. 직원 대화의 ID 공간도 사용자 대화와 분리한다.

클라이언트의 `id_verified`, `consent`, 사용자 ID, `session_id`, 가린 이름/신분 값은 인증 증거가 아니다.
공개 토큰 발급·로그인 성공 버튼을 추가하지 않았다. 서버가 권한 있는 인증 저장소에서 확인한 값만 사용한다.
인증 연결을 설정하지 않으면 기존 시연 동작과 실제 검색의 인증 잠금을 유지한다.
새 작업 조회 경로도 인증 연결을 설정했을 때만 등록한다. 미설정 모드에는 경로가 없다(404).

## 런타임 설정

`.env.example`에 이름만 추가했다. 실제 `.env`를 읽거나 수정하지 않았다.
운영자가 안전한 서버 런타임에 다음 설정을 주입해야 한다. 코드가 `.env` 파일을 자동으로 열지 않는다.

| 이름 | 용도 |
|---|---|
| `LF_CHAT_DATABASE_URL` | 기존 실제 물건 검색용 읽기 전용 DB 연결 |
| `LF_CHAT_SESSION_DATABASE_URL` | 아래 서버 소유 인증 읽기 뷰가 있는 DB 연결 |
| `LF_CHAT_BINDING_KEY_HEX` | 32~64바이트 고정 HMAC 키의 16진수 표현. 인증 발급/작업 생산자와 결합 규칙을 맞춤 |
| `LF_CHAT_OPERATION_DATABASE_URL` | 선택. 아래 영수증 읽기 뷰가 있는 DB 연결 |

인증 DB·키가 일부만 설정됐거나 키가 잘못되면 시작 설정 오류로 막는다. 약한 기본 키나 시연 인증으로 바꾸지 않는다.
DB 오류 때 시연 물건을 대신 보여주지 않는다. 비밀번호·연결 문자열·토큰·원문 사용자 ID는 오류/응답/그래프에 넣지 않는다.
키와 서버 인증 세션은 재시작 후에도 유지해야 한다. 키 교체·세션 갱신/이전은 별도 운영 계약이다.

## 인증 담당자가 제공할 읽기 뷰

`PostgresFindSessions`는 `chat_find_session_access`의 다음 칸을 고정 SQL로 읽는다.
이 이름은 **연결할 인터페이스 제안**이다. 기존 팀 DB에 이런 뷰가 이미 있다고 가정하지 않는다.
런타임에 테이블/뷰/세션을 생성하지 않으며 `center/schema.sql`이나 마이그레이션도 수정하지 않았다.

| 칸 | PostgreSQL 값/의미 |
|---|---|
| token_hash | 64자리 소문자 16진수, 아래 HMAC으로 결합한 토큰. 유일해야 함 |
| subject_id | 인증 서버가 정한 불투명 사용자 ID. 이름·주민번호 아님 |
| auth_session_id | 인증 서버가 발급한 실제 세션 ID. 브라우저 대화 번호 아님 |
| expires_at | timestamptz, 현재 시각보다 뒤여야 함 |
| id_verified_at | timestamptz, 실제 본인인증 완료 시각. 미완료는 NULL |
| consented_at | timestamptz, 필수 동의 완료 시각. 미완료는 NULL |
| revoked_at | timestamptz, 철회/차단되면 값 존재 |
| permissions | text[]: `chat:use`, `chat:search`, `chat:operations:read` 중 허용 범위 |

`FindSessionAuth`는 매 요청 새로 확인하고 성공 결과를 캐시하지 않는다. 검색/후보 선택도 검증기를 다시 통과한다.
모든 인증 조건에 더해 요청별 권한이 필요하다. 토큰 존재나 truthy 값만으로 통과시키지 않는다.
동일 토큰 조회가 여러 행을 반환하면 인증을 거절한다. 철회가 즉시 반영되는 권위 저장소를 사용해야 한다.
지연 복제본의 오래된 인증 결과를 최신 결과로 취급하지 않는다.

토큰 결합 규칙 버전 1:

```python
token_hash = binding_digest(binding_key, 'find-token-v1', bearer_token)
```

`binding_digest`는 JSON `[domain, value]`를 UTF-8, ensure_ascii=False, sort_keys=True,
separators=(',', ':'), allow_nan=False로 직렬화한 뒤 HMAC-SHA256을 계산한다.
기존 인증 서버의 토큰 저장 방식이 다르면 담당 서버에서 안전한 어댑터/매핑을 제공해야 한다.
실제 본인인증·동의를 검증하지 않은 가상 행을 운영에 넣어 기능을 여는 방식은 사용하지 않는다.

DB 직접 조회가 아닌 인증 서버 내부 함수를 사용할 경우에도 `FindSessionAuth(lookup, binding_key)`로 주입할 수 있다.
`lookup(token_hash)`는 신뢰된 서버의 `FindSession` 또는 None을 반환해야 한다. 클라이언트 JSON을 변환해 주입하면 안 된다.
현재 외부 인증 서버의 주소/API 계약은 제공되지 않아 실제 서비스와의 매핑은 남아 있다.

## 작업 영수증 담당자가 제공할 읽기 뷰

`PostgresOperationResults`는 `chat_operation_receipt_access`의
`operation_id`, `owner_scope`, `kind`, `request_hash`, `state`, `result`(jsonb)를 읽는다.
`operation_id`는 `op_`+32자리 소문자 16진수이며, ID+소유자 조건이 모두 같은 행 하나만 허용한다.

```python
owner_scope = binding_digest(binding_key, 'owner', [subject_id, auth_session_id])
```

이 규칙은 `04fc1ad`의 `OperationJournal`과 같다. 새 연결 때문에 이전 결합 규칙을 바꾸지 않았다.
`kind`는 found/lost/answer/cancel_claim, `state`는 prepared/running/uncertain/completed/rejected다.
완료 결과는 허용한 결과 ID만 받으며, 완료가 아닌 상태의 결과는 빈 객체여야 한다.
타인 작업과 없는 작업은 같은 404를 반환한다. DB 장애·이상한 영수증은 503으로 숨김 없이 알리되 내부 정보는 내보내지 않는다.
조회가 끝난 뒤에도 인증을 다시 확인해 그 사이 만료/철회됐으면 결과 ID를 반환하지 않는다.

응답 예:

```json
{"operation_id":"op_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","kind":"found","state":"uncertain","result":{},"retry_allowed":false}
```

소유자 해시·요청 해시·인증 정보는 응답에 넣지 않는다. 인증된 답변/결과 응답은 Cache-Control: no-store다.
이 GET은 **조회만** 한다. 장부 상태 변경·새 작업 생성·자동 재저장·불명 해제·로봇 실행을 하지 않는다.
영수증 생산자는 실제 업무 DB 변경과 같은 트랜잭션에 영수증을 확정해야 한다.
유사 물건 검색이나 기존 접수 번호만으로 과거 불명 작업의 성공 영수증을 만들면 안 된다.

## DB 접근 권한과 검증

인증/영수증 연결 계정은 담당 읽기 뷰에 대한 SELECT만 부여하고 업무 저장·인증 발급 권한을 주지 않는다.
고정 SQL·매개변수·읽기 전용 REPEATABLE READ·3초 statement_timeout·5초 연결 제한을 사용한다.
DB 운영자는 조회 대상 스키마/search_path를 고정하고 신뢰하지 않는 사용자의 CREATE 권한을 제거해야 한다.

대역+HTTP 시험은 `tests/test_chat_find_access.py`다. 별도 실제 PostgreSQL 시험은
`LF_CHAT_ACCESS_TEST_DSN`을 설정한 **폐기용 DB 이름 `lf_chat_access_test`에서만** 실행된다.
해당 시험은 임의 이름의 시험 스키마를 만들고 제거한다. 팀 DB에서 실행하지 않는다.
현재 Docker 엔진과 시험 DB가 없어 실제 PostgreSQL 시험은 실행하지 못했다.

## 이번 연결에 포함되지 않은 운영 활성화

- 인증 발급 서버/API와 위 인증 읽기 뷰의 실제 매핑·배포.
- 팀 DB에 영속 수락 초안·업무 변경·영수증을 원자적으로 저장하는 창구 구현/배포.
- 인증된 사용자 작업 조회 결과를 IntakeAgent의 불명 대화 상태에 자동 적용하는 복구.
- 재시작/새 대화/다른 화면에서 미확정 작업을 복원하는 연결, 운영자 대조·보관 정책.
- 실물 로봇/운영 DB/클라우드 검증. 최신 main 20개 후속 커밋 통합은 별도 기능 브랜치에서 완료했다(`2026-11-11-latest-team-integration.md`).

현재 코드는 필요한 설정/신뢰 계약이 충족될 때 실제 조회 경로를 열 수 있는 연결부다.
인증 발급 서비스와 실제 DB 연결이 확인되기 전에는 운영 활성화 완료라고 설명하지 않는다.

## 11/11 사용자 세션 발급 기반 후속

외부 발급 서버 정보가 확인되지 않아 프로젝트 안에 서버 내부 발급·저장·철회 부품을 추가했다.
`docs/design/find_session_lifecycle.md`와 검토용 `docs/contracts/chat-session-storage.sql`을 참고한다.
실제 본인인증/동의 권위 조회와 안전한 토큰 전달 경로는 미연결이며, 공개 발급 경로나 운영 활성화는 추가하지 않았다.

11/11 추가 후속: 서버 원본 저장/조회 어댑터와 발급기 연결은 `docs/design/identity_evidence.md`에 정리했다.
검토용 세션 조회 뷰는 현재 인증/동의/제공자/정책과 결합해, 원본 철회가 기존 토큰도 막도록 보완했다.
실제 인증 수집기와 네이티브 PostgreSQL 검증/배포는 여전히 남아 있다.

네이티브 시험 준비는 `tests/test_chat_identity_postgres.py`에 추가했다. 기존 읽기 어댑터 시험과 같은 폐기용 DB를 사용하되,
별도의 UUID 스키마에서 원본 인증 DDL·쓰기·동적 조회를 검증한다. DB가 없어 실행은 제외했다.
