# 분실물 후보 찾기 API — `POST /api/lost/search` (LF-5, 11/5 변재원)

한줄 설명: 분실인이 "무슨 물건을, 언제·어디서 잃어버렸는지" 보내면 보관 중인 습득물 중 **후보 최대 3개**를 돌려주는 공용 엔진이다.
챗봇(`/chat/questions`)의 물건 검색 에이전트와 **같은 엔진**(`agents/chat_search.py` `SearchAgent`)을 쓴다. 화면(키오스크 분실접수 탭, 분실인 웹)은 이 주소를 부르기만 하면 된다.

- 담당: 엔진·API 변재원(챗봇 쪽) / 화면 연결 김재민 / 본인인증 확인 함수 LF-6
- 코드: `agents/chat_api.py`(경로) · `agents/chat_search.py`(검색·인증·후보 번호표) · 시험 `tests/test_chat_api.py`
- 운영 지표: 이 주소의 건수·응답 시간은 `GET /chat/metrics` 의 `requests.lost_search` 에 쌓인다(입력값은 저장하지 않음)

## 1. 요청
```http
POST /api/lost/search
Content-Type: application/json
Authorization: Bearer <본인인증 세션 토큰>     ← 실제 팀 DB 모드에서만 필요(가상 DB 시연은 없어도 됨)

{"category": "지갑", "color": "검정", "lost_date": "2026-11-04", "lost_line": "1호선", "lost_station": "서울역",
 "description": "검정 반지갑, 키링 달림"}
```
| 칸 | 필수 | 뜻 |
| --- | --- | --- |
| `category` | 예 | 품목 6종 중 하나(`agents/contracts.py` CATEGORIES: 지갑·휴대폰·USB·립밤·보조배터리·핸드크림) |
| `color` | | 색(예: 검정) |
| `lost_date` | 실제 DB 에선 예 | 분실 날짜 `YYYY-MM-DD` — 이 날짜 이후 접수된 물건만 |
| `lost_line` | 실제 DB 에선 예 | 호선(예: 1호선) |
| `lost_station` | 실제 DB 에선 예 | 역 — 그 역을 먼저, 없으면 같은 호선 |
| `description` | | 자유 설명(500자까지만 사용). 비우면 "색 + 품목"으로 찾음 |

- 위 6칸 외의 칸을 보내거나 `category` 가 없으면 **422**(오타를 조용히 무시하지 않기 위해)
- 키링 같은 추가 특징은 아직 검색 점수에 반영하지 않는다(응답 `message` 에도 적힘)

## 2. 응답 (200)
```json
{"status": "items_found",
 "message": "조건에 맞는 후보 2개를 찾았어요. 본인 물건으로 확정된 결과는 아닙니다. …",
 "candidates": [{"candidate_no": 1, "category": "지갑", "color": "검정"},
                {"candidate_no": 2, "category": "지갑", "color": "검정"}],
 "search_result_id": "후보 번호표(임의 문자열)",
 "database_mode": "demo_sqlite",
 "search_filter": {"category": "지갑", "color": "검정", "lost_date": "2026-11-04", "...": "..."},
 "item_search_performed": true,
 "reservation_created": false}
```
| `status` | 뜻 | 화면에서 |
| --- | --- | --- |
| `items_found` | 후보 있음 | 후보 카드(품목·색·번호)만 보여 줌. "후보는 본인 물건 확정이 아님" 문구 필수 |
| `items_not_found` | 조건에 맞는 후보 없음 | "색·품목을 다시 확인" 안내. 물건이 **없다고 확정한 것은 아님** |
| `search_needs_details` | 품목·색을 못 알아봄, 또는 실제 DB 에서 날짜·호선·역이 빠짐 | 빠진 칸 입력 요청 |

- 후보에는 **접수 번호(item_id)·역·사진·점수가 없다**(남의 물건 정보를 흘리지 않기 위해). 화면은 `candidate_no` 와 `search_result_id` 만 들고 있는다
- `database_mode`: `demo_sqlite`(가상 물건 DB 시연 — 화면에 "가상 DB 시연" 배지) / 그 밖의 값(실제 팀 DB)
- 이 주소는 **예약·신청을 만들지 않는다**(`reservation_created: false` 고정)

## 3. 오류
| 코드 | 언제 | 화면에서 |
| --- | --- | --- |
| 401 | 실제 팀 DB 모드인데 서버가 확인한 본인인증 세션이 없음 | 본인인증 단계로 돌려보냄 |
| 422 | 본문이 틀림(칸 이름·category 없음·description 이 글자가 아님) | 입력 확인 |
| 503 | 챗봇 부품이 설치되지 않았거나, 물건 DB 가 연결되지 않았거나, 조회 실패 | "잠시 후 다시" |

## 4. 인증 — 누가 실제 DB 를 볼 수 있나
- 가상 DB(`TOWER_CHAT_DEMO_DB`) 모드: 누구나(시연용 가짜 물건만 있음)
- 실제 팀 DB(`LF_CHAT_DATABASE_URL`) 모드: `SearchAgent(database, authorize=…)` 의 **`authorize(token)` 함수가 `True` 를 돌려줄 때만** 검색한다
  - 화면이 보내는 "인증했음" 같은 값은 믿지 않는다. 서버가 토큰을 직접 확인한다
  - 지금은 `authorize` 가 연결되지 않아 실제 DB 모드는 항상 401 — **LF-6 본인인증 세션 확인 함수를 여기에 연결해야 열린다**(TBD, 아래 6절)

## 5. 후보를 고른 다음 — 실제 접수 번호는 서버 안에서만
- 분실인이 후보 2번을 고르면 화면은 `search_result_id` + `candidate_no` 를 서버로 보낸다
- 서버는 `SearchAgent.resolve_candidate(search_result_id, candidate_no, token)` 로 실제 `item_id` 를 얻는다. 이 함수를 부르는 **공개 주소는 일부러 만들지 않았다**(번호만 바꿔 남의 물건 번호를 캐는 것을 막기 위해)
- 지금 `POST /api/lost/claims` 는 본문에 `item_id` 를 직접 받는다. 화면에 실제 번호를 내려보내지 않으려면 다음 중 하나가 필요하다(TBD, 재민님과 결정)
  1. (추천) `/api/lost/claims` 가 `search_result_id`·`candidate_no` 도 받아 서버 안에서 `resolve_candidate` 로 `item_id` 를 채움
  2. 가상 DB 시연 동안만 지금처럼 `item_id` 를 쓰고, 실제 DB 를 열 때 1번으로 바꿈

## 6. 화면 연결 순서 (재민님)
1. 키오스크 분실접수 탭 / 분실인 웹의 "후보 찾기" 버튼 → `fetch("/api/lost/search", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(입력값)})`
2. `status` 별로 2절 표대로 화면 표시. 401·503 은 3절 표대로
3. 후보를 고르면 `search_result_id`·`candidate_no` 를 보관 → 신청 단계로(5절)
4. 실제 DB 로 넘어갈 때: 본인인증 후 받은 세션 토큰을 `Authorization: Bearer …` 로 함께 보냄 + LF-6 확인 함수 연결(변재원과 같이)

## 7. 시험
- 저장소: `python -m unittest tests.test_chat_api` (`LostSearchAndMetricsTest`: 정상·422·401·503·지표)
- 관제탑 켠 뒤 손으로(PowerShell):
  ```powershell
  $b = [Text.Encoding]::UTF8.GetBytes('{"category":"지갑","color":"검정"}')
  Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8100/api/lost/search -ContentType "application/json; charset=utf-8" -Body $b
  ```
