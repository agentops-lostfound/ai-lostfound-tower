# 본센터 보관함 정답지 (LF-8 · 11/6 변재원)

한줄 설명: **"물건 X 는 보관함 몇 행 몇 번 칸에 있고, 로봇팔은 어느 저장 자세로 가야 하는가"** 를 팀 DB 에 남기고, 비전(김건태) `run_storage_check.py` 가 읽는 storage JSON 으로 내보낸다.

- 표: `center/migrations/007_storage_slots_1106.sql` + 사진 반영 `008_storage_layout_photo_1106.sql`·`009_storage_categories_photo_1106.sql` (관제탑 켤 때 `tools/db_migrate.py --apply` 가 자동 적용, dev 모드로 켜 둔 채 `git pull` 했다면 직접 `--apply`)
- 코드: `agents/storage.py` (메모리·PostgreSQL 저장소), 관리자 API `/api/admin/storage*`, 내보내기 `tools/storage_export.py`
- 시험: `tests/test_storage.py`, `tests/test_service.py`(경로)

## 1. 왜 필요한가 (흐름)
```
등록기계 접수 → 회수 → 본센터 도착(본센터 보관)
   → 직원이 칸에 넣고 "넣기"(assign)          ← 정답지: 물건 번호 ↔ 칸
   → 분실인이 찾음 → Qwen 특징으로 후보 매칭
   → YOLO 가 그 물건이 있는 "행"만 잘라 개수 확인 ← 정답지: 그 행에 몇 개 있어야 하나
   → 로봇팔이 그 칸의 저장 자세로 가서 집기      ← 정답지: 칸 ↔ 저장 자세
   → 인계 구역(제출보관함)에 놓음 → 인계 대기(칸 예약 유지) → 직원 교차 검증 → 인계 완료 → 칸 자동 비움(DB 트리거)
                                                  → 틀리면 반환 보류 → 원래 칸으로 되돌림(docs/design/handover_cross_check.md)
```
YOLO 는 "어디에 무엇이 몇 개 보이나"만 안다. **어느 물건이 어느 칸인지는 DB 가 정답**이고, YOLO 는 그 정답과 개수가 맞는지 확인하는 역할이다.

## 2. 배치 (11/6 판 사진 기준)
보관판 긴 변 약 50cm × 짧은 변 약 25cm(로봇팔 받침 쪽 1.5cm 띠 포함 26.5cm). 긴 변 한쪽에 로봇팔, **반대쪽 긴 변 바깥에 제출보관함(20×20cm)**.
한 행 = 짧은 변 방향으로 받침 2개, 행 4개가 긴 변 방향으로 늘어선다(위에서 내려다본 그림, 탑뷰 카메라 기준).

```
                 [ArUco ID0]
        +--------------------------+
        |   R1-1           R1-2    |   R1 model phone, diagonal
        |   (wider gap, own pose)  |      -> gap to R2 is larger
        |                          |
 robot  |     R2-1       R2-2      |   R2 USB / cream / battery   +-----------+
 arm  ==+                          |                              |  H-1      |
 mount  |     R3-1       R3-2      |   R3 lip balm                |  handover |
        |                          |                              |  20x20cm  |
        |     R4-1       R4-2      |   R4 wallet (card + bifold)  +-----------+
        +--------------------------+
 [ArUco ID1]
              [yellow basket = glare shield, not a slot]
```
- 칸 번호 = `행-번호`(예: `R1-2`), 왼쪽(1)·오른쪽(2)은 탑뷰 그림 기준(추정 — 비전 영역 이름과 맞춰 확정)
- **R1(모형폰)**: 가로로 두면 인식이 잘 안 돼 폰을 **사선**으로 둔다. 받침 간격이 다른 행보다 넓고 R2 와도 멀다 → 저장 자세와 비전 영역을 R1 만 따로 잡는다(행마다 영역 1개라 코드는 그대로)
- **H-1 제출보관함**: 로봇팔 받침 반대쪽 긴 변 바깥, 대략 R2~R3 옆(008 마이그레이션 메모)
- **노란 바구니**: 빛 반사로 인식이 흔들려 세운 **가림막**이다. 보관 칸·인계 구역이 아니므로 DB 에 넣지 않는다
- 행별 품목은 판 사진에 맞춰 **팀이 정한 시연 시작값**(009): R1 모형폰 · R2 USB·핸드크림·보조배터리(사진에서 빈 행) · R3 립밤 · R4 지갑(카드지갑·반지갑). 바꾸려면 `storage_section.allowed_categories` 만 고치면 된다(코드 수정 불필요). 다른 품목을 굳이 넣을 때는 `override_category: true`

## 3. 표 4개
| 표 | 무엇 | 핵심 규칙 |
| --- | --- | --- |
| `storage_section` | 행(구역) R1~R4 + 인계 구역 H | `allowed_categories`(빈 배열 = 제한 없음), `bounds_mm`(작업대 mm, 선택) |
| `storage_slot` | 칸 9개 | `pose_name` = 로봇 티칭에서 정한 저장 자세 이름(티칭 전 NULL, 영문 소문자로 시작) |
| `storage_assignment` | 지금 어느 칸에 어느 물건 | 칸 하나에 물건 하나(PK), 물건 하나는 칸 하나(UNIQUE). **인계 완료가 되면 자동 삭제**(트리거, 11/6 011 — 인계 대기·반환 보류 동안은 원래 칸 예약) |
| `inventory_check` | 탑뷰 개수 확인 기록 | `run_storage_check.py` 결과 status 그대로(count_match 등). 개인정보 없음 |

보관함 위에 있다고 보는 상태는 비전과 같게 `본센터 보관 · 확인 중 · 승인·수령 예약` 3개다. `반환 중`(로봇이 집는 중)은 칸 기록은 남기되 내보내기에서는 뺀다(집기에 실패하면 그대로 그 칸에 있으므로).

## 4. 관리자 API (로그인 필요)
| 방법 | 주소 | 본문 예 | 결과 |
| --- | --- | --- | --- |
| GET | `/api/admin/storage` | - | 행·칸·저장 자세·들어 있는 물건(번호·상태·품목만) + 요약(빈 칸, 자세 없는 칸) |
| GET | `/api/admin/storage/export` | - | 비전 storage JSON(아래 5장) |
| POST | `/api/admin/storage/assign` | `{"item_id": "A-W01", "slot_id": "R4-1"}` | 넣기. 다른 물건이 있으면 409, 보관함 상태가 아니면 409, 품목이 다르면 422 |
| POST | `/api/admin/storage/release` | `{"slot_id": "R4-1"}` 또는 `{"item_id": "A-W01"}` | 칸 비우기 |
| POST | `/api/admin/storage/slots/{slot_id}/pose` | `{"pose_name": "pose_1"}` (`null` = 지움) | 저장 자세 연결 |
| POST | `/api/admin/storage/checks` | `{"section": "R1", "expected_count": 2, "detected_count": 2, "status": "count_match"}` | 개수 확인 기록 |
| GET | `/api/admin/storage/checks?limit=20` | - | 최근 기록 |

`TOWER_DB=1` 이면 팀 DB, 아니면 관제탑이 켜져 있는 동안만 기억(시연 부품 A-W01~ 로 시험 가능).

## 5. 비전 storage JSON (김건태 `run_storage_check.py --storage`)
```json
{
  "sections": {
    "R1": {"label": "1행 모형폰", "kind": "shelf", "slots": {"1": "pose_1", "2": "pose_2"}},
    "H":  {"label": "인계 구역(제출보관함)", "kind": "handover", "slots": {"1": "handover"}}
  },
  "inventory": {"A-20261106-0001": {"section": "R1", "slot": "2"}},
  "warnings": [],
  "exported_at": "2026-11-06T05:00:00+00:00"
}
```
- `load_storage` 가 읽는 `sections[행]["slots"][칸]`, `inventory[물건]["section"/"slot"]` 모양 그대로다(`label`·`kind`·`warnings` 는 더해진 칸이라 무시됨)
- `bounds_mm` 는 값이 있을 때만 들어간다. 지금 비전은 화면에서 저장한 픽셀 영역(`regions.json`)을 쓰므로 **영역 이름을 행 코드(R1~R4)와 같게** 저장하면 바로 맞물린다
- 물건이 있는 칸에 저장 자세가 비어 있으면 `warnings` 에 적고, 비전도 그 파일을 거절한다(안전: 자세 없이 로봇을 움직이지 않음)

만드는 법(저장소 폴더, `.venv`, 팀 DB 켠 상태):
```
python tools/storage_export.py --out data/storage.json
```
- DB 없이 형식만: `python tools/storage_export.py --demo`
- 끝 코드: 0 정상 · 1 DB 못 읽음 · 2 저장 자세 빠진 칸 있음

## 6. 다음 할 일
| 할 일 | 누가 |
| --- | --- |
| ~~로봇 티칭으로 칸 8개 + H-1 저장 자세 이름 정하기~~ → 11/6 완료(8장, 013 마이그레이션) | 김건태·변재원 |
| 비전 영역 이름을 R1~R4 로 저장 | 김건태 |
| 관리자 화면에 보관함 칸 보기·넣기 버튼 | 변재원 |
| 본센터 도착 시 빈 칸 자동 추천(품목 → 행) | 변재원 |

## 7. 본센터 도착 처리 — 직원 보관 화면(11/6)
관리자 화면(`/admin`) → **보관함** 탭(`/storage-desk`).

```
역 키오스크 접수(등록기계 보관, 사진·Qwen 특징)  ──(직원이 1시간마다 회수)──▶  본센터
   보관 화면 "도착 대기": 본센터에 있음(본센터 접수·본센터 보관) / 역 키오스크 상자 안(회수해 온 뒤 넣기)
   물건 고르기 → 품목에 맞는 빈 칸 추천(같은 목록에서 같은 칸을 두 번 추천하지 않음)
   실제로 넣은 뒤 "이 칸에 넣었음" → 상태 본센터 보관 + 칸 기록 + 상태 기록(changed_by=staff)을 거래 하나로
```
- 추천 순서: 그 품목을 받는 행의 빈 칸 → 품목 제한 없는 행 → 아무 빈 보관 칸(다른 행 표시). 품목을 모르면(확인 불가) 추천하지 않고 직원이 사진을 보고 고른다
- 다른 행에 넣거나 품목 미확인이면 `override_category` 가 필요하다(화면: 확인 체크, 품목 미확인은 자동)
- 칸 관리(접힌 메뉴): 칸 비우기, 저장 자세 이름 연결(로봇 티칭 담당)
- API: `GET /api/admin/storage/arrivals`, `POST /api/admin/storage/arrivals/{item_id}/place` `{"slot_id": "R4-1", "override_category": false}`
- 시연 데이터 주의: `center/seed_demo.sql` 의 A-W01~W07 은 모두 지갑(옛 가짜 탑뷰 시연용)이라 지갑 행(2칸)이 금방 찬다 → 나머지는 다른 행으로 추천된다

## 8. 칸 ↔ 로봇 저장 자세 (11/6 김건태 확정, 013)
한줄 설명: 로봇팔이 칸마다 **미리 티칭해 둔 자세 이름**(`pose_1`~`pose_8`)으로 가서, 거기서부터 집기 모델(SmolVLA)이 집는다. 좌표 계산(IK)은 쓰지 않는다(11/5 김건태 결정).

| 행 | 1(로봇팔 가까운 칸) | 2(먼 칸) |
| --- | --- | --- |
| R1 모형폰 | `pose_1` | `pose_2` |
| R2 USB·핸드크림·보조배터리 | `pose_3` | `pose_4` |
| R3 립밤 | `pose_5` | `pose_6` |
| R4 지갑 | `pose_7` | `pose_8` |
| H-1 제출보관함(배출구) | `close` | |

- 반환 한 번의 로봇 동작: **칸 자세(pose_N)** → 집기·들어 올리기(SmolVLA) → **배출구 순서** `outlet_return_1 → close → open → outlet_return_1 → home`(`agents/storage.py` `OUTLET_SEQUENCE`)
- 자세 값(관절 6개)의 원본은 김건태 PC `outputs/robot_panel_live/poses.json`(Studio normalized 단위 -100~100, 각도·mm 아님). DB 에는 **이름만** 둔다. 다른 팔·다른 보정이면 그 값을 그대로 쓰지 않고 다시 티칭한다
- 013 은 **비어 있는 칸만** 채운다(보관함 화면에서 직접 바꾼 이름은 그대로). 관제탑이 켜져 있지 않을 때(메모리 보관함·가상 시연)도 같은 연결표(`SLOT_POSES`)를 쓴다
- 11/7 가상 시연(`TOWER_SIM=1`)의 작업대 그림(`/live`·`/admin`)도 이 4행×2칸 + H-1 배치로 그린다. 가상 물건이 칸에 놓이면 정답지에도 같은 칸이 기록되고(로봇이 넣는 순간 '회수 중'이어도 도착 처리), 직원이 칸을 고르면 그림도 따라간다 — `agents/sim_director.py` `link_storage`
- 반환을 시작하면 관제 기록에 "보관 칸 R4-2 · 자세 pose_8" 처럼 남는다(로봇에 자세 이름을 실제로 보내는 연결은 로봇 계약 변경 뒤 — `docs/contracts/robot_api.md`, 팀 확인 필요)
- Studio 쪽 자세 이동 통로(김건태 11/6, 설치 전): 같은 런타임 WebSocket 에 `{"event":"move_saved_pose","data":{"pose":"pose_1",...}}` + 200ms 마다 heartbeat, `saved_pose_status=arrived` 가 도착 확인. 집기 성공 자동 판정·배출구 연속 실행은 아직 없음

