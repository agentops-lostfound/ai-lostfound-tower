# 관제탑 ↔ 로봇팔 API (11/5 재정립)

한줄 설명: 관제탑은 "어디로 가서 집어 바구니에 놓아라" 같은 **의미 명령**만 보내고, 관절을 어떻게 돌릴지는 로봇 쪽이 정한다.
관제탑은 로봇 상태(단계·정지 여부·관절 6개)를 읽어 화면(`/live`)과 관제 채널에 보여 준다.

## 1. 층 구조
```
[관제탑 agents/]                 [로봇 서비스(미정·TBD)]                 [소유자 robot/]                [SO-101 팔로워]
 supervisor.py 반환 흐름  --1층-->  의미 명령 → 관절 목표                --2층-->  OwnerBridge(정지 관문)  -->  STS3215 모터 6개
 api.py /robot/stop·home·state     (접근=좌표 변환, 집기=SmolVLA,                  CommandGate
 robot_api.py 계약·검사             전달·원점=저장 경로)                          lf-owner-safety-v1(JSON)
 가상: sim_world.SimRobot  -------1층 그대로(같은 함수 이름)
```
- **1층(이 문서의 주 계약)**: 관제탑이 부르는 함수 7개. 가상 로봇(`agents/sim_world.py` `SimRobot`)과 진짜 로봇이 **같은 이름·같은 결과 모양**을 쓴다
- **2층**: 순필님 `robot/owner_bridge.py` 의 JSON 명령(`status`·`stop`·`resume`·`action`). 관제탑은 2층을 직접 부르지 않는다(정지만 예외로 허용 검토, TBD)
- 가운데 "로봇 서비스"(의미 명령 → 관절 목표)는 아직 없다 → 김건태(LF-19·21 집기·좌표)·이순필(LF-11·12 정지·원점) 협의(TBD)

## 2. 1층 함수 (관제탑 → 로봇)
모든 함수는 `{ok: bool, reason: str}` 를 돌려준다(`agents/contracts.py` `robot_result`). 실패면 관제탑이 멈추고 알린다.

| 함수 | 담당 | 입력 | 하는 일 | 실패 때 관제탑 |
|---|---|---|---|---|
| `robot_approach(center_mm, center_px)` | 김건태 LF-21 | 작업대 mm `[x, y]`(이동 기준), 탑뷰 픽셀 `[cx, cy]`(참고) | 물건 위 사전 접근 자세로 이동 | 정지 + 알림. mm 가 없으면 부르지 않음 |
| `robot_grasp()` | 김건태 LF-19 | 없음 | 근거리 집기·들기(SmolVLA, 손목 카메라) | 1번 재시도 후 정지 |
| `robot_verify_grasp()` | 김건태 LF-19 | 없음 | 집게 닫힘 + 탑뷰로 집었는지 확인 | 실패 처리 |
| `robot_deliver()` | 이순필 LF-11 | 없음 | 바구니(수령대)까지 옮기고 집게 열기 | 정지 + 알림 |
| `robot_stop()` | 이순필 LF-11 | 없음 | **그 자리에서 즉시 정지만**(원점 복귀 안 함). 반환 중에도 동작 | "전원 차단·확인" 알림 |
| `robot_home()` | 이순필 LF-11 | 없음 | 저장된 경로로 원점(접힌 대기 자세, `robot/config/home_pose.json`) 복귀. 주변 확인 뒤 버튼으로만, 반환 중이면 거부 | 알림 |
| `robot_state()` (11/5 추가, 선택) | 로봇 부품 | 없음 | 지금 상태 읽기(아래 모양) | 없으면 화면에 "상태 없음" |

### `robot_state()` 결과 모양
```json
{"phase": "대기", "stopped": false, "holding": null,
 "joints": {"shoulder_pan": 0.0, "shoulder_lift": -34.3, "elbow_flex": 38.0,
            "wrist_flex": 83.5, "wrist_roll": 0.0, "gripper": 30.0},
 "source": "sim"}
```
- 관절 이름·순서·번호: `agents/sim_world.py` `SO101_JOINTS` (1 shoulder_pan … 6 gripper) — 순필님 `docs/progress/soarm-local-handoff.md` 와 같다
- 단위: 각도는 도(°, 공식 모델 so101_new_calib 기준 부호), `gripper` 는 % (0 닫힘 ~ 100 열림)
- 관절 한계: `SO101_LIMITS` (좌우 ±110 · 숙임 ±100 · 접힘 ±96.8 · 손목 ±95 · 회전 -157~163)
- 진짜 로봇은 보정값(homing·min·max)으로 읽은 값을 이 단위로 바꿔 준다(TBD: 변환 함수 위치)
- `stopped=true` 면 화면 위쪽에 빨간 정지 띠, 원점 복귀 버튼만 허용

## 3. 안전 규칙 (관제탑이 지킴)
1. 승인 기록 없이 로봇을 움직이지 않는다(`db_set_status` 실패면 멈춤)
2. 보정이 없거나 믿을 수 없으면(`calibration_valid` 가 True 아님) mm 좌표가 없고, 관제탑은 `robot_approach` 를 부르지 않는다
3. 정지는 언제나 먼저. 정지 뒤 자동 재개 없음. 다시 움직이려면 원점 복귀(주변 확인) → 새 반환
4. 11/5 결정: **직원은 일단 제외** — 신분 확인은 본센터 키오스크가 직접(셀프). 지금 코드의 `staff_confirmed`(원점 복귀·인계 확인) 칸 이름은 그대로 두고 "현장 운영자 확인"으로 읽는다(이름 바꾸기는 키오스크 회수 화면을 만들 때 함께, TBD)

## 4. 2층과 맞추기 (제안, 순필님 확인 필요)
| 1층 | 2층(OwnerBridge `lf-owner-safety-v1`) |
|---|---|
| `robot_stop()` | `{"op": "stop", "session": …}` → `stop_requested` |
| `robot_state()` | `{"op": "status"}` → `stop_requested`·`hold_commanded`·`manual_pose`(최신 관측 위치) — 관절 값 칸 추가 필요(TBD) |
| `robot_home()` | `resume`(확인 표시) + 저장 경로를 `action` 목표 묶음으로 전송 — 경로 활성화 전(순필님: "일반 작업 자세에서의 복귀 경로는 아직 활성화하지 않음") |
| `robot_approach`·`grasp`·`deliver` | 로봇 서비스가 관절 목표를 만들어 `action`(sequence 증가)으로 보냄 — 서비스 미정 |

## 5. 연결하는 법 (관제탑 쪽)
- 진짜 로봇 부품은 1층 함수 6개(+선택 `robot_state`)를 가진 객체 하나면 된다
- `agents/backends.py` `CompositeBackend(robot=진짜부품)` 으로 꽂는다. 빠진 함수가 있으면 켤 때 오류로 알려 준다(`check_part`)
- 계약 검사 도구: `agents/robot_api.py` (`validate_robot_state`, `ROBOT_COMMANDS`)
- 화면: `GET /robot/state` (11/5 추가) → `/live` 로봇 카드가 진짜 부품일 때도 관절 값을 보여 줄 수 있게

## 6. DB 칸 모드(11/9 추가) — 탑뷰 없이 칸 저장 자세로
- `.env TOWER_ROBOT_TARGET=db` 면 반환 흐름이 `robot_approach` 대신 선택 함수 **`robot_go_pose(pose_name, slot_id)`** 를 부른다(번호 1~8 → `pose_1~8`)
- 로봇 부품 꽂기 `.env TOWER_ROBOT_PART=모듈:클래스`, 읽는 주소 `GET /api/admin/storage/robot-target/{item_id}` · `/robot-targets`
- 전체 설명·뼈대 코드·체크리스트: `docs/contracts/robot_db_target.md`

## TBD
- 로봇 서비스(의미 명령 → 관절 목표)의 위치·담당
- OwnerBridge `status` 에 관절 값(°) 칸 추가 여부
- 본센터 키오스크 셀프 신분 확인 → 반환 승인 연결(키오스크 회수 화면)
