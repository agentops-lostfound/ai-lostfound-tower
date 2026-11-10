# 물건이 움직이면 DB는 어떻게 바뀌나 (11/10 · LF-8 · LF-18)

한줄 설명: 물건 하나가 키오스크에 접수되어 주인에게 돌아갈 때까지, **어느 동작(트리거)에서 어느 표가 어떻게 바뀌는지**를 순서대로 정리한 설명서. 표 정의는 `database.md`, 상태 값 목록은 `agents/contracts.py ITEM_STATUS`.

- 확인 방법: 팀 DB와 같은 표 정의(center/schema.sql + migrations 001~018)를 넣은 시험용 PostgreSQL 16 에서 가상 시연 한 바퀴를 실제로 돌려 단계마다 표를 읽었다(11/10). 아래 값은 그 결과
- 11/11 무인 인계(6단계 `changed_by = kiosk`)는 시험용 PostgreSQL 16 에서 `tests.test_db_mirror` 로 다시 확인했다(인계 완료 기록 + 트리거가 보관 칸 행 삭제)
- 관제탑 PC 의 실제 팀 DB 에 DBeaver 로 접속해 본 결과는 아니다. 실물 로봇을 연결한 실행에서는 5단계의 `return_step` 이름·줄 수가 다를 수 있다

## 0. 한눈에 보기

```text
키오스크 / 챗봇·분실인 웹 / 직원 화면
        │ 요청
        ▼
관제탑(파이썬, 포트 8100) ── 챗봇 판단 과정 ──▶ Langfuse(인터넷 서비스, DB 아님)
        │ INSERT · UPDATE · DELETE
        ▼
팀 DB(PostgreSQL 16, Docker 컨테이너 lostfound-db, 127.0.0.1:5434)
        ▲ SELECT(읽기만)
        │
DBeaver · /showcase [팀 DB 조회]
```

- 화면은 DB 에 직접 쓰지 않는다. 모든 쓰기는 관제탑을 거친다
- 물건 1개 = `item` 1행. 움직일 때마다 `item.status` 가 UPDATE 되고, 그때마다 `item_status_log` 에 "무엇에서 무엇으로·누가·언제" 1줄이 INSERT 된다
- 가상 시연(`TOWER_SIM=1`)은 메모리의 시연 세계를 먼저 바꾸고 같은 내용을 팀 DB 에도 쓴다(`agents/db_mirror.py`). 팀 DB 가 꺼져도 시연은 계속된다. 가상 물건은 `item.object_id = 'SIM'`, 키오스크 사진 접수는 진짜 접수라 표시 없음

## 1. 상태 흐름과 기록자

| 순서 | 계기 | `item.status` | `changed_by` |
|---|---|---|---|
| 1 | 키오스크 등록 | 등록기계 보관 | kiosk |
| 2 | 직원이 꺼냄 | 회수 중 | staff |
| 3 | 보관 칸에 넣음 | 본센터 보관 | staff |
| 4 | 방문 · 메인 AI 승인 | 승인·수령 예약 | tower |
| 5 | 로봇이 꺼내는 중 | 반환 중 | tower |
| 6 | 제출보관함 도착 | 인계 대기 | tower |
| 7 | 분실인이 제출보관함에서 꺼내고 키오스크 [물건 받았어요] (11/11 무인 인계) | 인계 완료 | kiosk (예외 흐름은 직원 교차 검증 → staff) |

예외 흐름(확인 질문 미통과·직원 보관 선반)에서 직원 교차 검증이 맞지 않으면 "반환 보류" 옆길로 빠진다(위 표는 정상 흐름만).

## 2. 동작별로 바뀌는 표

| 단계(트리거) | 표 | 명령 | 값 (11/10 확인) |
|---|---|---|---|
| 1 키오스크 등록 | `item` | INSERT | `item_id` A-20261110-0002 · `machine_id` KIOSK-A · `place_text` 해운대역 승강장 · `status` 등록기계 보관 · `category` 확인 불가 · `photo_path` 사진 위치(사진은 DB 밖 파일) |
| | `finder_contact` | INSERT | 연락처를 입력했을 때만 |
| | `item_status_log` | INSERT | (없음) → 등록기계 보관, kiosk |
| 2 Qwen 사진 분석 | `item` | UPDATE | `category` → 핸드크림 · `features` 색 초록·모양 tube · `private_features` 확인 질문 정답(공개 칸과 분리) |
| 3 회수·보관 | `item` | UPDATE ×2 | 등록기계 보관 → 회수 중 → 본센터 보관 |
| | `item_status_log` | INSERT ×2 | staff |
| | `storage_assignment` | INSERT | `slot_id` R3-2 (R3-1 은 시연용 분홍 핸드크림) |
| 4 분실 접수 | `claim` | INSERT | C-20261110-0001 · `description` 핸드크림·초록 · `lost_station` 해운대 · 가린 이름·가린 신분 번호 |
| | `quiz_attempt` | INSERT | `field` place · `passed` true (답은 저장 안 함) |
| | `reservation` | INSERT | `item_id` A-20261110-0002 · `status` booked |
| | `item` | 변화 없음 | 여전히 본센터 보관 |
| 5 방문·반환 | `reservation` | UPDATE | booked → visited |
| | `item` | UPDATE ×3 | 본센터 보관 → 승인·수령 예약 → 반환 중 → 인계 대기 |
| | `item_status_log` | INSERT ×3 | tower |
| | `return_case` | INSERT | R-C-20261110-0001 · `decision` returned · `reason` 제출보관함 전달 완료 · 인계 대기(분실인이 꺼내고 키오스크 확인, 예외는 직원) — 11/11 문구 |
| | `return_step` | INSERT ×8 | 메인 AI 승인 · 수령 예약 → 직원 확인 완료 → 탑뷰 촬영 → 매칭 완료 → GPU 사용권 받음 → 사전 접근 완료 → 집기 성공 → 제출보관함 전달 완료 |
| 6 인계 완료 | `item` | UPDATE | 인계 대기 → 인계 완료 (키오스크 [물건 받았어요], 11/11) |
| | `item_status_log` | INSERT | kiosk (예외 흐름의 직원 교차 검증이면 staff) |
| | `storage_assignment` | DELETE | R3-2 행 삭제 = **DB 트리거**가 스스로 지움 |
| 찾기 요청 취소(방문 전) | `reservation` | UPDATE | booked → cancelled (`claim`·`quiz_attempt` 는 기록으로 남고 물건은 같은 칸에 그대로) |

- 5단계에서 보관 칸을 바로 지우지 않는 이유: 교차 검증이 틀리면 물건을 **원래 칸**에 되돌려야 하므로 인계 완료까지 칸을 잡아 둔다(`011_storage_release_on_done_1106.sql`)
- DB 가 스스로 실행하는 트리거는 `storage_release_on_handover` 하나다(`item.status` 가 인계 완료가 되면 그 물건의 `storage_assignment` 행 삭제). 나머지 변화는 모두 관제탑 코드가 보낸다

## 3. 직접 확인하기

### DBeaver
Database → New Database Connection → PostgreSQL → Host `127.0.0.1`(다른 PC 는 관제탑 PC 주소, `web/README.md` 5-1) · Port `5434` · Database·Username `lostfound` · Password 는 관제탑 PC `.env` 의 `POSTGRES_PASSWORD`(문서·메신저에 적지 않음) → Test Connection → Finish → lostfound → Schemas → public → Tables. **읽기만 한다**(칸을 직접 고치면 관제탑과 어긋남). `finder_contact` 는 개인정보라 화면에 띄우지 않는다.

```sql
-- 물건 하나가 지나온 길 (설명에 가장 좋음: 한 바퀴면 7줄)
SELECT from_status, to_status, changed_by, at
FROM item_status_log WHERE item_id = 'A-20261110-0002' ORDER BY id;

-- 최근 접수와 지금 상태
SELECT item_id, status, category, place_text, received_at FROM item ORDER BY received_at DESC LIMIT 10;

-- 보관 칸
SELECT a.slot_id, a.item_id, i.category, i.status FROM storage_assignment a JOIN item i USING (item_id) ORDER BY a.slot_id;

-- 찾기 요청과 예약
SELECT c.claim_id, c.lost_station, r.item_id, r.status FROM claim c JOIN reservation r USING (claim_id) ORDER BY c.created_at DESC;

-- 반환 결과와 단계
SELECT case_id, item_id, decision, reason FROM return_case ORDER BY created_at DESC LIMIT 5;
SELECT step, at FROM return_step WHERE case_id = 'R-C-20261110-0001' ORDER BY id;

-- DB 에 걸린 트리거
SELECT tgname, tgrelid::regclass FROM pg_trigger WHERE NOT tgisinternal;
```

### Docker (관제탑 PC, 저장소 폴더)
| 할 일 | 명령 | 정상 |
|---|---|---|
| 켜져 있나 | `docker ps` | `lostfound-db`, `lostfound-web` |
| 켜기 | `docker compose up -d` | Started / Running (`tools\start_tower.bat` 가 함께 켬) |
| 로그 | `docker logs lostfound-db --tail 20` | ready to accept connections |
| 표 목록 | `docker exec -it lostfound-db psql -U lostfound -d lostfound -c "\dt"` | 표 이름 목록 |

`docker compose down -v` 는 팀 DB 데이터를 모두 지우므로 쓰지 않는다.

### 발표 화면
`/showcase` 의 "DB 실시간 기록" 칸에 표·칸·값이 일어나는 즉시 나타나고, [팀 DB 조회] 로 팀 DB 에 실제로 들어간 최근 접수와 표별 행 수를 본다. 이름·전화번호·가린 신분 번호·확인 질문 정답은 값 대신 "저장됨"만 보인다(`agents/db_watch.py`).

## 4. Langfuse 와의 차이

| | 팀 DB | Langfuse |
|---|---|---|
| 적는 것 | 일의 결과(물건·요청·예약·반환) | 챗봇 에이전트가 판단한 과정(coordinator → planner → supervisor ⇄ 일꾼, 모델 입·출력, 시간) |
| 위치 | 관제탑 PC Docker | 인터넷 서비스(us.cloud.langfuse.com) |
| 보는 법 | DBeaver | 웹 로그인 → Tracing → Traces |
| 꺼지면 | 기록이 남지 않음 | 챗봇은 그대로, 과정 기록만 빠짐 |

챗봇 답이 이상하면 DB 가 아니라 Langfuse 에서 그 질문의 trace 를 연다. 설정은 `chatbot_sllm_rag.md` §11.
