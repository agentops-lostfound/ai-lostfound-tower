# 로봇팔 ↔ DB 연결 — 탑뷰(YOLO) 없이 DB 칸 번호 1~8 로 움직이기 (LF-8 · 11/9 변재원)

한줄 설명: 분실물 번호를 주면 DB 가 "그 물건은 몇 번 칸(1~8)에 있고, 로봇팔은 저장 자세 `pose_N` 으로 가면 된다"를 알려 주고,
관제탑 반환 흐름이 그 자세로 로봇팔을 보낸다. 탑뷰 카메라(YOLO)는 나중에 붙여도 된다.

받는 사람: 김건태님과 김건태님의 Codex(로봇팔 부품을 만들고 실물에 연결). 이 문서 하나만 읽고 작업을 시작할 수 있게 썼다.

---

## 0. AI(Codex·Claude)가 이 문서로 작업할 때 지킬 규칙
1. 로봇을 움직일지 말지는 **관제탑 코드가 정한다**. 로봇 부품은 "받은 명령을 안전하게 수행하거나 실패를 `{ok: false, reason}` 으로 돌려주는 것"만 한다
2. 실패·애매함은 언제나 **멈추는 쪽**. 예외를 던지지 말고 `{"ok": false, "reason": "…"}` 로 돌려준다(관제탑이 정지 + 직원 알림)
3. `.env`(비밀값)는 읽거나 출력하거나 커밋하지 않는다. 필요한 이름만 `.env.example` 에 적는다
4. 계약(함수 이름·결과 모양, `agents/contracts.py`, 이 문서)을 바꾸면 PR 에 이유를 적고 변재원 확인을 받는다
5. 브랜치 `LF-번호-geontae-…`, 커밋 `LF-번호 무엇을 왜(한국어)`, main 직접 push 금지, force push 금지
6. 코드를 바꾸면 `python -m unittest discover -s tests` 통과 확인(Windows 에서 돌리면 GUI 시험 9개도 같이 돈다)

---

## 1. 결론 먼저
| 질문 | 답 |
|---|---|
| 번호 순서는? | **로봇 가까운 줄 1·3·5·7, 먼 줄 2·4·6·8**. 탑뷰에서 왼쪽 열(R1)부터 오른쪽 열(R4) |
| 번호 → 자세는? | **번호 N = 저장 자세 `pose_N`** (Studio·티칭 GUI 의 "커스텀 N" 버튼과 같은 이름) |
| 물건 → 번호는 어디서? | DB 표 `storage_assignment`(물건이 든 칸) + `storage_slot`(칸의 자세 이름) |
| 로봇 PC 는 무엇을 읽나? | `GET /api/admin/storage/robot-target/{물건번호}` (한 물건) · `GET /api/admin/storage/robot-targets` (8칸 전체) |
| 관제탑이 로봇을 부르는 법은? | `.env` `TOWER_ROBOT_TARGET=db` 면 반환 흐름이 `robot_go_pose(pose_name, slot_id)` 를 부른다 |
| 로봇 부품을 꽂는 법은? | `.env` `TOWER_ROBOT_PART=모듈:클래스` (예 `robot.tower_part:TowerRobot`) |
| 김건태님이 만들 것 | 로봇 부품 클래스 1개(함수 7개) — 9장 뼈대 그대로 시작 |

---

## 2. 용어
| 말 | 뜻 |
|---|---|
| 칸(slot) | 보관판 위 물건 한 개 자리. `R1-1` ~ `R4-2` 8칸 + 제출보관함 `H-1` + 직원 보관 선반 `S-n` |
| 열(column, section) | 같은 품목을 두는 세로 두 칸 묶음 `R1`~`R4`. DB 표 이름은 `storage_section`(예전 이름 '행' 그대로) |
| 줄(row) | `near`(로봇 가까운 줄, 칸 이름 끝 `-1`, 홀수 번호) · `far`(먼 줄, `-2`, 짝수 번호) |
| 번호(number) | 사용자가 부르는 1~8. 코드 `agents/storage.py SLOT_NUMBERS` |
| 저장 자세(pose) | 미리 티칭해 둔 관절값 6개 묶음의 이름. 값은 로봇 PC 파일(`poses.json`·Studio `saved_poses.json`)에, **이름만 DB 에** |
| 배출구 순서 | 집은 뒤 제출보관함(H-1)에 놓는 순서 `outlet_return_1 → close → open → outlet_return_1 → home` |
| DB 칸 모드 | 탑뷰 좌표 대신 DB 칸·저장 자세로 접근하는 반환 방식(`TOWER_ROBOT_TARGET=db`) |
| 탑뷰 모드 | 예전 방식. 탑뷰 카메라가 찾은 물건 중심 mm 좌표로 접근(`robot_approach`) — 기본값 |

---

## 3. 실물 배치와 번호 (탑뷰, 위에서 내려다봄)
```
                      (로봇 반대쪽)
                 +---[ H-1 submit box 200x200 ]---+
   +-------------+-------------+-------------+-------------+
   |  2  R1-2    |  4  R2-2    |  6  R3-2    |  8  R4-2    |   far  (-2)
   |  pose_2     |  pose_4     |  pose_6     |  pose_8     |
   +-------------+-------------+-------------+-------------+
   |  1  R1-1    |  3  R2-1    |  5  R3-1    |  7  R4-1    |   near (-1)
   |  pose_1     |  pose_3     |  pose_5     |  pose_7     |
   +-------------+-------------+-------------+-------------+
      phone(/45)    card wallet   power bank    hand cream
                         [ SO-101 robot arm ]
```
- 보관판 약 500 × 250 mm, 테두리 마킹테이프 15 mm. H-1 은 보관판 위쪽(로봇 반대쪽) 가운데에 붙어 있다
- 열 품목(11/9 확정, 016 마이그레이션): R1 휴대폰(목업폰, '/' 45도 — 카메라 쪽이 오른쪽 위) · R2 카드지갑 · R3 보조배터리 · R4 핸드크림
- 번호 ↔ 자세 연결 근거: 11/6 김건태님 확정(013 마이그레이션 "각 행 1(로봇 가까운 칸) = pose_1·3·5·7, 2(먼 칸) = pose_2·4·6·8")
- ⚠️ 11/9 에 열마다 품목을 바꿨지만 **칸 위치 자체는 그대로**라 자세를 다시 티칭할 필요는 없다(추정). 12장 체크리스트 1번으로 실물 확인

---

## 4. DB 전체 구조 (A부터 Z까지)
PostgreSQL 16 · 기본 `center/schema.sql` + 바뀐 점 `center/migrations/001~016` (`python tools/db_migrate.py --apply`).
그림·결정 이유 전체는 `docs/design/database.md`. 아래는 로봇 연결에 필요한 순서대로.

### 4-1. 표 지도
```
machine --< item >-- place
             |  \
             |   +--< item_status_log        (상태가 바뀐 기록)
             |   +--- finder_contact          (습득자 연락처, 직원만)
             |   +--< collection_item >-- collection   (역 등록기계 -> 본센터 회수)
             |   +--< claim_candidate >-- claim --< quiz_attempt, reservation (분실인 찾기)
             |   +--< return_case --< return_step       (반환 기록)
             |
             +--- storage_assignment >-- storage_slot >-- storage_section   (보관함: 로봇 연결의 중심)
                                                   inventory_check --^     (탑뷰 개수 확인 기록)
```

### 4-2. 표별 한 줄 설명
| 묶음 | 표 | 한 줄 설명 | 로봇 연결에 쓰나 |
|---|---|---|---|
| 기준 | `machine` | 역 습득물 등록기계·본센터 목록(KIOSK-A 해운대 등) | - |
| 기준 | `place` | 습득 장소 추천 목록 | - |
| 접수 | **`item`** | 물건 1개 = 1행. 번호·품목·상태·공개 특징·사진 경로 | ✅ 번호·품목·상태 |
| 접수 | `finder_contact` | 습득자 연락처(선택). 인계 완료 30일 뒤 삭제 | ❌ 개인정보 — 읽지 않음 |
| 접수 | `item_status_log` | 상태가 언제 누가 무엇에서 무엇으로 바뀌었나 | 참고 |
| 회수 | `collection`·`collection_item` | 역 등록기계 → 본센터 회수 묶음 | - |
| 찾기 | `claim`·`claim_candidate`·`quiz_attempt`·`reservation` | 분실인 찾기 요청·후보·확인 질문·방문 예약 | - |
| 반환 | `return_case`·`return_step` | 반환 한 번의 결정·단계 기록(관제탑이 씀) | 참고(단계 기록) |
| 보관함 | **`storage_section`** | 열 R1~R4 · 인계 구역 H · 직원 보관 선반 S | ✅ |
| 보관함 | **`storage_slot`** | 칸 R1-1~R4-2 · H-1 · S-n 과 **저장 자세 이름** | ✅ |
| 보관함 | **`storage_assignment`** | 지금 어느 칸에 어느 물건이 있나(칸 1 = 물건 1) | ✅ |
| 보관함 | `inventory_check` | 탑뷰 개수 확인 결과(YOLO 붙인 뒤) | 나중에 |

### 4-3. 로봇 연결에 쓰는 표의 칸(전부)
**`item`** (물건)
| 칸 | 모양 | 뜻 |
|---|---|---|
| `item_id` | `A-20261109-0001` 또는 `A-W01` | 물건 번호(PK). 형식 `^[A-Z]-([0-9]{8}-[0-9]{4}\|W[0-9]{2})$` |
| `category` | `지갑`·`모형폰`·`보조배터리`·`핸드크림`(운영 4종) | 품목. 옛 기록용으로 `USB`·`립밤`·`확인 불가` 도 허용 |
| `status` | 아래 5장 | 물건 상태 |
| `features` | JSON `{color, shape, material, confidence}` | 공개 특징(사진 분석) |
| `private_features` | JSON | 비공개 특징(확인 질문 정답) — **로봇 쪽은 읽지 않는다** |
| `photo_path`·`object_id`·`machine_id`·`place_text`·`received_at`·`updated_at` | | 사진 경로·시연 ID·접수 기계·장소·시각 |

**`storage_section`** (열)
| 칸 | 지금 값 | 뜻 |
|---|---|---|
| `section_code` | `R1`·`R2`·`R3`·`R4`·`H`·`S` | 열 이름(PK) |
| `label` | `R1 휴대폰 전용`·`R2 카드지갑`·`R3 보조배터리`·`R4 핸드크림`·`인계 구역(제출보관함)`·`직원 보관 선반` | 화면 이름 |
| `kind` | `shelf`(R1~R4) · `handover`(H) · `staff`(S) | 로봇이 집는 곳은 `shelf` 만 |
| `allowed_categories` | `{모형폰}`·`{지갑}`·`{보조배터리}`·`{핸드크림}` | 열에 넣을 수 있는 품목 |
| `bounds_mm` | 지금 모두 `NULL` | 작업대 mm `[x1, y1, x2, y2]`(ArUco 기준). 탑뷰 붙일 때 `/storage` 화면에서 채움 |
| `sort_order` | 1~6 | 화면 순서 |

**`storage_slot`** (칸)
| 칸 | 지금 값 | 뜻 |
|---|---|---|
| `slot_id` | `R1-1` … `R4-2`, `H-1`, `S-1`… | 칸 이름(PK) |
| `section_code` | `R1`… | 속한 열 |
| `slot_no` | 1(로봇 가까움) · 2(먼 쪽) | 열 안 순서 |
| `pose_name` | `pose_1`~`pose_8`, H-1 은 `close` | 저장 자세 이름. 형식 `^[a-z][a-z0-9_]{0,31}$`. 티칭 전이면 `NULL` |
| `note` | `45도 사선·상단 오른쪽 위` 등 | 메모 |

**`storage_assignment`** (지금 칸에 든 물건)
| 칸 | 뜻 |
|---|---|
| `slot_id` | 칸(PK) — 칸 하나에 물건 하나 |
| `item_id` | 물건(UNIQUE) — 물건 하나는 칸 하나 |
| `assigned_at`·`assigned_by` | 언제 · 누가(`staff`·`tower`·`system`) |
| 자동 비우기 | 물건 상태가 `인계 완료` 가 되면 DB 트리거가 이 행을 지운다(11/6, 011 마이그레이션) |

번호 1~8 은 **DB 칸이 아니라 코드에서 계산**한다(`SLOT_NUMBERS`). 칸 이름(`R3-2`)에서 바로 나오므로 마이그레이션이 필요 없고, 두 곳이 어긋날 일이 없다.

### 4-4. 물건 하나의 위치를 SQL 로 직접 보기(확인용, 읽기만)
```sql
SELECT i.item_id, i.category, i.status, a.slot_id, s.pose_name, sec.kind
FROM storage_assignment a
JOIN item i            ON i.item_id = a.item_id
JOIN storage_slot s    ON s.slot_id = a.slot_id
JOIN storage_section sec ON sec.section_code = s.section_code
WHERE i.item_id = 'A-20261109-0001';
```
로봇 부품은 SQL 을 직접 쓰지 말고 7장 API 를 쓴다(권한·형식 검사가 API 에 있음).

---

## 5. 물건 상태 흐름(누가 바꾸나)
```
등록기계 보관 -> 회수 중 -> 본센터 보관 -> 승인·수령 예약 -> 반환 중 -> 인계 대기 -> 인계 완료
   (키오스크)    (회수)     (직원이 칸에 넣음)  (관제탑 승인)    (로봇 출발)  (제출보관함)  (직원이 건넴)
                                  ^                                  |
                                  +------ 반환 보류 / 실패 되돌림 -----+
```
- 로봇이 움직이는 구간은 `반환 중` 하나뿐. 관제탑이 상태를 `반환 중` 으로 **기록한 뒤에만** 로봇을 부른다(기록 실패면 안 움직임)
- 로봇이 물건을 건드리기 전에 끝나면(자세 없음·GPU 없음 등) 관제탑이 상태를 `본센터 보관` 으로 되돌린다

---

## 6. 물건 번호 → 로봇 움직임까지 (DB 칸 모드)
```
[분실인 승인]  -> 관제탑 TowerService.start_return
                    1. DB: 물건 상태 확인(본센터에 있나)
                    2. DB: 칸 찾기  storage_assignment -> storage_slot -> 번호·pose_name   (svc.robot_target)
                    3. 직원 보관 선반이면 로봇 안 씀(직원 인계)
                 -> 반환 흐름 agents/supervisor.py
                    web_gate -> visit_gate -> shelf_handover
                    locate   : "DB 칸 위치 사용(탑뷰 없음) R3-2 · 번호 6 · 자세 pose_6"   (탑뷰·매칭 건너뜀)
                    approach : 칸·자세 확인 -> GPU 사용권 -> 상태 '반환 중' -> robot_go_pose("pose_6", "R3-2")
                    grasp    : robot_grasp() -> robot_verify_grasp()  (실패면 1번 더, 그래도 실패면 정지)
                    deliver  : robot_deliver()  (배출구 순서) -> 상태 '인계 대기'
                 -> 직원이 분실인에게 건넴 -> '인계 완료' -> 칸 자동 비움
```
안전 장치(모두 시험 있음, 13장):
| 상황 | 관제탑 동작 |
|---|---|
| 칸 기록 없음·자세 이름 없음·인계 구역 칸 | 로봇 안 움직임 → 직원 확인(이유 문장에 무엇이 없는지) |
| 로봇 부품에 `robot_go_pose` 가 없음 | 로봇 안 움직임 → 직원 확인. **가짜 부품이 대신 '성공'하지 않는다** |
| `robot_go_pose` 실패 | `robot_stop` → 정지 + 알림 |
| 직원 화면 정지 버튼을 눌렀음 | 그 뒤 `robot_go_pose`·집기·전달 요청은 부품에 보내지 않고 실패 처리 |
| 반환 요청 본문에 칸을 넣어 보냄 | 무시(칸은 서버가 DB 로만 정함) |
| 화면에서 자세 이름을 번호와 다르게 바꿈(예 R2-1 에 `pose_1`) | 움직이긴 하되 `warnings` 에 "번호대로의 pose_3 과 다름" |

---

## 7. API (로봇 PC 가 읽는 주소)
관제탑 주소: 교육원 `http://10.10.21.21:8100`(관제탑 PC, `start_tower.bat lan`) · 같은 PC 면 `http://127.0.0.1:8100`.
관리자 API 라서 `LF_ADMIN_PASSWORD` 가 켜져 있으면 머리글 `X-Admin-Key: <.env 의 LF_ADMIN_API_KEY>` 가 필요하다(값은 문서·코드에 쓰지 않음).

### 7-1. 한 물건 — `GET /api/admin/storage/robot-target/{item_id}`
로봇을 움직이지 않고 읽기만 한다. 성공 예(11/9 실제 PostgreSQL 에서 찍은 값):
```json
{"ok": true, "item_id": "A-W31", "slot_id": "R3-2", "column": "R3", "category": "보조배터리",
 "number": 6, "row": "far", "pose_name": "pose_6", "pose_expected": "pose_6", "bounds_mm": null,
 "outlet_sequence": ["outlet_return_1", "close", "open", "outlet_return_1", "home"], "warnings": []}
```
실패 예(`ok: false` 와 `code`):
| code | 뜻 | 할 일 |
|---|---|---|
| `no_slot` | 칸 기록 없음 | `/storage` 화면에서 칸에 넣은 기록부터 |
| `no_pose` | 칸에 자세 이름 없음(`pose_expected` 에 넣을 이름) | `/storage` 화면 또는 7-3 으로 연결 |
| `staff_shelf` | 직원 보관 선반 물건 | 로봇 안 씀 |
| `not_robot_slot` | 인계 구역 등 1~8 밖 | 로봇 안 씀 |
| `db_error` | DB 읽기 실패 | 관제탑·DB 확인 |
물건 번호 형식이 틀리면 422.

### 7-2. 8칸 전체 — `GET /api/admin/storage/robot-targets`
```json
{"mode": "db",
 "numbering": "로봇 가까운 줄 1·3·5·7, 먼 줄 2·4·6·8 (탑뷰 왼쪽 R1 → 오른쪽 R4), 번호 N = 저장 자세 pose_N",
 "outlet_sequence": ["outlet_return_1", "close", "open", "outlet_return_1", "home"],
 "slots": [
  {"number": 1, "slot_id": "R1-1", "column": "R1", "label": "R1 휴대폰 전용", "row": "near",
   "pose_name": "pose_1", "pose_expected": "pose_1", "item_id": null, "category": null, "bounds_mm": null},
  "... 2~8 같은 모양 ..."]}
```
`mode` 는 지금 관제탑 설정(`db`·`vision`).

### 7-3. 이미 있던 주소(같이 쓰는 것)
| 주소 | 하는 일 |
|---|---|
| `GET /api/admin/storage` | 보관함 전체(열·칸·물건·요약) |
| `POST /api/admin/storage/slots/{slot_id}/pose` `{"pose_name": "pose_6"}` | 칸에 자세 이름 연결(null = 지움) |
| `POST /api/admin/storage/assign` `{"item_id", "slot_id"}` | 물건을 칸에 기록(직원 화면이 씀) |
| `GET /api/admin/storage/export` | 비전 `run_storage_check.py --storage` 형식(탑뷰 붙일 때) |
| `GET /robot/state` | 로봇 부품의 `robot_state()`(있으면) — `/live` 화면 |
| `POST /api/robot/stop` | 정지(로그인 없이 항상 열림) |

---

## 8. 관제탑 쪽 설정 (`.env`, 관제탑 PC)
| 이름 | 값 | 뜻 |
|---|---|---|
| `TOWER_ROBOT_TARGET` | `db` | 반환 때 DB 칸 저장 자세로 접근(탑뷰 없이). 비우면 예전(탑뷰) |
| `TOWER_ROBOT_PART` | `robot.tower_part:TowerRobot` | 진짜 로봇 부품 클래스. 비우면 가짜 로봇 |
| `TOWER_DB` 등 | 기존 그대로 | 팀 DB 연결 |
- `TOWER_SIM=1`(가상 시연)에서도 `TOWER_ROBOT_TARGET=db` 를 주면 가상 로봇이 칸 위치로 움직이는 것을 `/live` 에서 볼 수 있다
- 관제탑을 켤 때 부품에 필수 함수가 없으면 바로 오류로 알린다(`agents/robot_part.py`)

---

## 9. 김건태님이 만들 것 — 로봇 부품 클래스(뼈대)
파일 예: `robot/tower_part.py` (이름은 자유, `TOWER_ROBOT_PART` 에 맞춤). 인자 없이 만들 수 있어야 한다.
```python
"""관제탑 반환 흐름에 꽂는 SO-101 로봇 부품 (LF-21 · 김건태) — docs/contracts/robot_db_target.md 9장"""
from agents.contracts import robot_result      # {"ok": bool, "reason": str}


class TowerRobot:
    def __init__(self):
        # TODO(김건태): 저장 자세 값 읽기(poses.json / Studio saved_poses.json), 로봇 연결 준비
        self.poses = {}                       # {"pose_1": [6개 값], ...}

    # --- DB 칸 모드(11/9 새로) ---
    def robot_go_pose(self, pose_name: str, slot_id: str) -> dict:
        """저장 자세 pose_name(pose_1~8) 으로 이동해 '물건 위 사전 접근' 상태가 되면 ok.
        slot_id 는 기록·확인용(R3-2 등). 모르는 자세 이름이면 움직이지 말고 실패로"""
        if pose_name not in self.poses:
            return robot_result(False, f"저장 자세 없음: {pose_name}")
        # TODO: 3·4·5초 보간 이동(Studio 저장 자세 방식) → 도착 확인
        return robot_result(True)

    # --- 필수 6개(docs/contracts/robot_api.md) ---
    def robot_approach(self, center_mm, center_px) -> dict:   # 탑뷰 모드용. 아직이면 실패로 두면 됨
        return robot_result(False, "탑뷰 접근 아직 없음 — TOWER_ROBOT_TARGET=db 로 쓰세요")
    def robot_grasp(self) -> dict: ...         # 집게 닫고 안전 높이로(SmolVLA 또는 정해 둔 내리기·닫기)
    def robot_verify_grasp(self) -> dict: ...  # 집게 닫힘 정도로 집었는지
    def robot_deliver(self) -> dict: ...       # 배출구 순서 outlet_return_1 → close → open → outlet_return_1 → home
    def robot_stop(self) -> dict: ...          # 그 자리 즉시 정지만(원점 복귀 안 함)
    def robot_home(self) -> dict: ...          # 저장 경로로 원점(직원 버튼으로만)

    def robot_state(self) -> dict:             # 선택: /live 화면에 관절 값 표시
        return {"phase": "대기", "stopped": False, "holding": None, "joints": {}, "source": "so101"}
```
- 이동 구현 후보(추정, 김건태님 판단): 티칭 GUI 가 쓰는 `robot/vendor_backend.py` `VendorBackend.start_stage(target, …)`(WSL LeRobot 작업자) 또는 Studio 확장의 저장 자세 실행(`robot/studio_extension/runtime/saved_pose.py`, 3·4·5초·심장박동). 관제탑은 어느 쪽이든 상관없다
- 모든 함수는 **오래 걸려도 끝날 때 결과를 돌려준다**(동기). 정지 버튼은 다른 스레드에서 `robot_stop()` 을 부르므로, 이동 중에도 멈출 수 있어야 한다
- 예외 대신 `robot_result(False, 이유)`. 이유 문장은 직원 알림에 그대로 나간다(개인정보 넣지 않기)

### 9-1. requirements(설치 목록)에 넣을 정보
한줄 설명: 로봇 부품은 **관제탑 파이썬(`.venv`) 안으로 불러와져(import) 돈다** → 부품이 `import` 하는 패키지는 관제탑 설치 목록에 있어야 한다.

| 어디서 도나 | 설치 목록 파일 | 지금 들어 있는 것 | 로봇 부품 때문에 더 넣을 것 |
|---|---|---|---|
| 관제탑 `.venv`(Windows, 관제탑 PC) — **로봇 부품 클래스가 여기서 돈다** | `agents/requirements.txt` | fastapi·uvicorn·psycopg[binary]·numpy·pyyaml·langgraph·langfuse·mcp·Pillow | 부품이 표준 라이브러리 + numpy 만 쓰면 **없음**. 그 밖의 패키지를 `import` 하면 그 이름을 여기에 한 줄씩 |
| 티칭·제어 창(`robot/teaching_gui.py`, `control_panel.py`) 전용 가상환경 | `robot/requirements-panel.txt` | numpy·opencv-python·websocket-client | 관제탑과 별개(관제탑이 쓰지 않음) |
| LeRobot·모터 제어(WSL 안 Docker `physical-ai-studio-cuda`) | 컨테이너 안(관제탑 설치 목록에 넣지 않음) | lerobot·feetech 등 | 관제탑 `.venv` 에 lerobot·torch 를 넣지 않는다(6GB GPU·설치 충돌) |

- 11/9 확인(실제 코드 읽음): `robot/vendor_backend.py`·`joint_motion.py`·`panel_core.py`·`owner_bridge.py`·`command_gate.py` 는 **표준 라이브러리만** 쓴다(`subprocess` 로 WSL 작업자를 부름). 이 길로 만들면 관제탑 설치 목록에 더할 것이 없다
- `robot/panel_transport.py` 를 그대로 부르면 `websocket-client` 가 필요할 수 있다(추정) — 그때 `agents/requirements.txt` 에 `websocket-client` 한 줄
- 넣는 법: 한 줄에 패키지 하나, 위에 `# 로봇 부품(LF-21) — 무엇 때문에` 주석. 버전은 꼭 필요할 때만(`이름>=버전`). 넣은 뒤 관제탑 PC 에서
  ```powershell
  .\.venv\Scripts\python.exe -m pip install -r agents\requirements.txt
  ```
- 확인: `python -c "from agents.robot_part import load_robot_part; load_robot_part('robot.tower_part:TowerRobot')"` 가 오류 없이 끝나면 설치 목록이 맞다

---

## 10. 연결 순서 (김건태님 체크리스트)
1. 저장소 최신화 후 브랜치 만들기
   - Windows 터미널 → PowerShell 탭 → 저장소 폴더
   ```powershell
   cd C:\git\ai-lostfound-tower
   ```
   ```powershell
   git pull
   ```
   ```powershell
   git checkout -b LF-21-geontae-tower-robot-part
   ```
2. 9장 뼈대로 `robot/tower_part.py` 만들기 → `robot_go_pose` 부터(나머지는 처음엔 실패로 둬도 됨)
3. 가짜 관제탑 없이 부품만 시험: `python -c "from agents.robot_part import load_robot_part; p=load_robot_part('robot.tower_part:TowerRobot'); print(p.robot_go_pose('pose_1','R1-1'))"`
4. 관제탑 PC `.env` 에 `TOWER_ROBOT_TARGET=db`, `TOWER_ROBOT_PART=robot.tower_part:TowerRobot` → `tools\start_tower.bat lan`
5. 브라우저 `http://10.10.21.21:8100/api/admin/storage/robot-targets` 로 8칸 자세 이름이 `pose_1~8` 인지 확인
6. `/storage` 화면에서 시험 물건을 칸에 넣기 → `/api/admin/storage/robot-target/{물건번호}` 로 번호·자세 확인
7. 로봇 주변을 비우고, 정지 버튼 위치를 확인한 뒤 반환 한 번 → `/live` 에서 단계 `DB 칸 위치 사용 → 사전 접근 완료 → 집기 → 제출보관함 전달` 확인
8. PR: 제목 `LF-21 관제탑 로봇 부품(DB 칸 모드) 추가`, 본문에 실물 확인 결과(칸별 성공 여부)

---

## 11. 이번에 찾아서 고친 문제 (11/9, 이 문서와 같은 PR)
| # | 문제 | 고친 것 |
|---|---|---|
| 1 | 반환 흐름이 탑뷰 좌표(`center_mm`)로만 접근 → YOLO 없이는 로봇이 절대 움직일 수 없었다 | DB 칸 모드(`TOWER_ROBOT_TARGET=db`): `locate` 가 DB 칸을 쓰고 `approach` 가 `robot_go_pose` 를 부름 |
| 2 | 로봇 PC 가 "물건 → 칸 → 자세"를 읽을 주소가 없었다 | `GET /api/admin/storage/robot-target/{item_id}`, `GET /api/admin/storage/robot-targets` |
| 3 | 사용자 번호 1~8(1357/2468)이 코드·DB 어디에도 없었다 | `agents/storage.py SLOT_NUMBERS` + 결과에 `number`·`row`·`pose_expected` |
| 4 | 진짜 로봇 부품을 관제탑에 꽂는 자리가 없었다(로봇 묶음은 늘 가짜) | `.env TOWER_ROBOT_PART` + `agents/robot_part.py`(형식·필수 함수 검사), 부품은 한 번만 만듦 |
| 5 | 진짜 로봇에 새 함수가 없으면 가짜 부품이 대신 '성공'할 수 있었다 | `CompositeBackend` 가 진짜 로봇이 꽂혀 있으면 그 부품 것만 쓰고, 없으면 직원 확인 |
| 6 | 정지 버튼 뒤에 새 이동 함수가 막히지 않을 수 있었다 | `ROBOT_MOVES` 에 `robot_go_pose` 추가 |
| 7 | 반환 요청 본문으로 칸을 넣어 엉뚱한 칸으로 보낼 수 있는 구멍 | `robot_target` 은 요청에서 받지 않음(서버가 DB 로만 정함) |
| 8 | 화면에서 자세 이름을 바꾸면 번호와 어긋나도 모름 | `warnings` 로 알림 |

---

## 12. 남은 문제 · TBD (숨기지 않음)
1. **실물 확인 필요**: `pose_1~8` 이 정말 위 그림의 칸 위인지(11/6 티칭 이후 판·카메라를 옮겼다면 다시 티칭) — 김건태님 확인
2. **DB 칸 모드는 사진 매칭을 하지 않는다**: 칸 기록이 틀리면(직원이 다른 칸에 넣고 기록) 엉뚱한 물건을 집는다. 지금 막는 장치는 직원 인계 때 교차 검증(`/staff`) — 탑뷰를 붙이면 "칸 범위 안에 물건이 있나" 확인을 더할 수 있다(`bounds_mm` 채우기, 에이전트 대화의 로봇팔 위치 확인과 같은 방식)
3. **집기 방법**: 저장 자세는 "물건 위"까지. 내려가서 집기를 SmolVLA 로 할지, 칸마다 정해 둔 내리기 자세로 할지 — 김건태님 결정(TBD)
4. **자세 값과 이름 동기화**: DB 에는 이름만 있다. 로봇 PC 의 `poses.json`·Studio `saved_poses.json` 이름이 `pose_1~8`·`close`·`open`·`outlet_return_1`·`home` 과 정확히 같아야 한다
5. `bounds_mm` 모두 비어 있음 → 탑뷰 붙일 때 `/storage` 화면 "구역 좌표"로 채움
6. 휴대폰 열(R1)은 45도 사선 — 집게 손목 회전(`wrist_roll`)이 자세에 들어 있는지 확인(TBD)

---

## 13. 시험 (실제로 돌린 것)
- `python -m unittest tests.test_robot_db_target` — 번호 규칙, 물건 → 자세, 칸·자세 없음, 선반, 이름 바꿈 경고, 반환 흐름(탑뷰 안 부름), 부품에 함수 없음, 이동 실패 정지, 탑뷰 모드 그대로, `.env` 스위치, 요청 본문 차단, 부품 꽂기·형식 오류 (14개)
- `tests/test_service.py` — 새 주소 2개(성공·no_slot·형식 오류 422·8칸 순서)
- 실제 PostgreSQL 16(마이그레이션 001~016 적용)에서 `PostgresStorageStore` 로 `A-W31 → R3-2 → 번호 6 → pose_6` 확인
- 가상 시연(`TOWER_SIM` 부품 + `TOWER_ROBOT_TARGET=db`)에서 습득 → 분실 → 반환이 `DB 칸 위치 사용(탑뷰 없음) R2-2 · 번호 4 · 자세 pose_4 → 사전 접근 완료 → 집기 성공 → 제출보관함 전달 → 인계 완료` 로 끝까지 돎
