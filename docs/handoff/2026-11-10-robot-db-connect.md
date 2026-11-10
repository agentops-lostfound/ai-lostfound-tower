# 로봇팔 ↔ 관제탑 DB 연결 — 이어서 할 일 (LF-21 · 11/10 변재원 → 김건태)

한줄 설명: 티칭이 끝난 저장 자세(`pose_1~8`)를 관제탑 DB 의 칸과 실제로 연결해 보는 단계. 이 문서는 **지금 어디까지 됐고, 김건태 님 PC 에서 무엇부터 하면 되는지**만 적는다.
자세한 약속은 `docs/contracts/robot_db_target.md`, 부품 설명은 `docs/handoff/2026-11-09-tower-robot-part.md`.

받는 사람: 김건태 님과 김건태 님의 Codex.

## 0. AI(Codex·Claude)가 지킬 규칙
- `.env`(비밀값)는 읽거나 출력하거나 커밋하지 않는다. 설정 이름만 다룬다
- 로봇을 실제로 움직이는 명령은 사람이 로봇 옆에서 정지 수단을 확인한 뒤에만 보낸다. 시험 통과 ≠ 실물 확인
- main 에 직접 push 하지 않는다. force push 하지 않는다. 이 브랜치(`LF-21-geontae-tower-robot-part`)에서 이어서 작업하고 PR #164 로 올린다

## 1. 지금 상태 (11/10 14시, 확인한 것만)
| 항목 | 상태 |
|---|---|
| 이 브랜치 | 최신 main 을 합쳐 충돌 해결됨(`.env.example` 한 곳, 양쪽 이름 모두 남김). 로봇 코드·자세 파일은 그대로 |
| 전체 시험 | 합친 상태로 1,363개 실행 — 클라우드에서 열 수 없는 화면 도구 시험 9개만 오류(기존과 같음). Windows 에서 다시 돌려 확인 필요 |
| PR #164 | 아직 병합 안 됨(병합은 변재원이 직접) |
| 관제탑(교육원 PC 3st11, `http://10.10.21.21:8100`) | 켜져 있음. 가상 시연 모드(`TOWER_SIM=1`) |
| 칸 ↔ 자세 | `GET /api/admin/storage/robot-targets` 로 확인: 1~8 = `R1-1`…`R4-2` = `pose_1`…`pose_8` 모두 연결됨 |
| 관제탑 반환 방식 | 아직 탑뷰 모드(`mode: "vision"`) — `TOWER_ROBOT_TARGET=db` 를 아직 안 넣음 |
| 관제탑의 로봇 | 가상 로봇(SimRobot). **가상 시연 모드는 지금 `TOWER_ROBOT_PART` 를 쓰지 않는다**(3장 2번) |

## 2. 김건태 님 PC 에서 먼저 할 일
1. 이 브랜치 받기 — Windows 터미널 → PowerShell 탭 → 저장소 폴더에서
   ```powershell
   git fetch origin
   ```
   ```powershell
   git status
   ```
   - 커밋하지 않은 작업이 있으면 먼저 커밋한다(오늘 티칭한 자세 파일 포함)
   ```powershell
   git pull origin LF-21-geontae-tower-robot-part
   ```
   - 로컬에만 있던 커밋과 합쳐진다. 충돌이 나면 그 파일 이름을 변재원에게 알린다
2. **오늘 티칭한 자세가 저장소에 있는지 확인** — 저장소의 `outputs/robot_panel_live/poses.json` 은 11/9 17:43 커밋이 마지막이다.
   오늘 값이 다르면 갱신해서 커밋·push 한다. Studio 의 저장 자세 이름·값과 같아야 한다(`pose_1~8`·`home`·`close`·`open`·`outlet_return_1`)
3. 부품이 불러와지는지만 확인(장비에 연결하거나 움직이지 않음)
   ```powershell
   .\.venv\Scripts\python.exe -c "from agents.robot_part import load_robot_part; from agents.robot_api import check_robot_part; print(check_robot_part(load_robot_part('robot.tower_part:TowerRobot')))"
   ```
4. 전체 시험
   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests
   ```
5. push 한 뒤 변재원에게 알림 → 변재원이 #164 를 병합

## 3. 정해야 할 것 (답을 주면 변재원 쪽에서 이어서 연결)
1. **로봇과 Studio 는 어느 PC 에 있나?** `TowerRobot` 은 Windows → `wsl.exe` → 같은 PC 의 Studio 컨테이너에 붙는다.
   그래서 **관제탑과 Studio 가 같은 PC** 여야 한다. 관제탑 PC(3st11)가 아니면 ① 관제탑을 로봇 PC 에서 켜거나 ② 로봇을 관제탑 PC 로 옮겨야 한다
2. **가상 시연 + 진짜 로봇**: 발표는 가상 시연 모드로 한다. 이 모드에서도 `TOWER_ROBOT_PART` 가 있으면 진짜 로봇 부품을 쓰도록 관제탑을 고치는 일은 변재원이 한다(#164 병합 뒤)
3. **발표에서 로봇을 어디까지 보일까?** 지금 부품은 `robot_go_pose`(사전 접근)·정지까지만 되고 집기·파지 확인·전달·원점은 실패를 돌려준다.
   - (가) 관제탑 반환 흐름 그대로: 칸 위 사전 접근까지 가고 집기에서 "직원 확인"으로 멈춤
   - (나) 집기 없는 시험 순서(`pose_N → outlet_return_1 → close → open → outlet_return_1 → home`, `robot/db_pose_sequence.py`)를 관제탑에서 부르기: 끝까지 움직이지만 물건은 집지 않음
   - (다) 집기 정책(VLA) 어댑터를 붙여 끝까지: `grasp_policy` 연결 + `robot_verify_grasp`·`robot_deliver`·`robot_home` 구현 필요
4. `TOWER_STUDIO_FOLLOWER_ID` 에 넣을 값(Studio 에 연결한 팔로워 ID)은 김건태 님이 알고 있다 — 값은 문서·메신저에 적지 말고 관제탑 PC `.env` 에 직접 넣는다

## 4. 관제탑 쪽 설정 (관제탑 PC `.env`, 값은 사람이 넣음)
| 이름 | 값 |
|---|---|
| `TOWER_ROBOT_TARGET` | `db` |
| `TOWER_ROBOT_PART` | `robot.tower_part:TowerRobot` |
| `TOWER_STUDIO_FOLLOWER_ID` | Studio 팔로워 ID |
| `TOWER_ROBOT_MOVE_SECONDS` | `3`(또는 4·5) |
| `TOWER_ROBOT_POSES` | 비우면 저장소 `outputs/robot_panel_live/poses.json` |

넣은 뒤 `tools\start_tower.bat lan` 으로 다시 켜고 아래로 확인한다(읽기만, 로봇은 움직이지 않음).
- `http://10.10.21.21:8100/api/admin/storage/robot-targets` → `"mode": "db"`
- `http://10.10.21.21:8100/api/admin/storage/robot-target/{물건번호}` → `number`·`pose_name` 이 실제 칸과 맞는지

## 5. 실물 시험 순서 (사람이 로봇 옆에 있을 때만)
1. Studio 를 켜고 팔 연결, HOLD·녹화 꺼짐 확인. 다른 창의 텔레·이동·녹화는 끈다
2. 로봇 주변을 비우고 정지 수단(화면 정지 버튼, 전원)을 확인
3. 빈 집게로 칸 하나(`pose_1`)부터 → 8칸 차례로. 칸마다 도착 여부를 기록
4. 그 다음에 3장 3번에서 정한 범위로 반환 한 번
5. 결과(칸별 성공 여부·걸린 시간·멈춘 곳)를 PR #164 에 적는다

## 6. 모르는 것 (TBD)
- 오늘 티칭한 자세 값이 저장소에 반영됐는지
- 휴대폰 열(R1, 45도)의 손목 회전이 자세에 들어 있는지
- 실물에서 8칸 모두 도착 기준(±5, 0.3초)을 통과하는지
