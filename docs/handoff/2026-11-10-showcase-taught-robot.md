# Showcase 회수 버튼 → 원격 티칭 로봇 · LF-21 · 2026-11-10

> 후속 진행: 사용자 승인으로 PR #203을 main `6c5cec2`에 병합했다. 재원님의 시작 시 번호 재정렬도 포함돼 있다. 로봇 PC는 이를 기존 브랜치로 통합했으며 관제탑 PC의 코드 갱신·설정·재시작 및 새 실물 시험은 아직 별도 단계다. 아래의 미병합/미게시 문구는 이전 기록이다.

## 현재 결과와 범위

- 기존 `LF-21-geontae-tower-robot-part` 브랜치에서 main `c9a5889`까지 fast-forward했다. 원격의 같은 이름 브랜치는 삭제된 상태였으며 새 브랜치를 만들지 않았다. 기존 미커밋 원격 작업은 임시 보관 후 복원했고 충돌은 없었다.
- 공유 브랜치는 `LF-21-geontae-tower-robot-part`다. 사용자의 11/10 마감 요청에 따라 커밋·푸시·PR로 공유하고 Jira LF-21을 갱신한다. main 자동 병합·관제탑 재시작·새 실물 시험은 하지 않는다. 비밀값 파일 `.env`도 읽거나 편집하지 않았다.
- 마감 시 실제 네트워크 확인: 로봇 PC에 인증된 LIVE 서버를 DISARMED로 기동했다. 사용자가 관제탑 PC에서 TCP 접속 및 인증된 `/v1/health` 응답(mode=live, armed=false, active_job 없음, 미확인 정지 없음, R1-1 허용 목록)을 확인해 전달했다. **두 PC 인증 상태 조회 성공**이며 실행 요청/완료 응답을 실물로 시험한 것은 아니다. Studio는 기존 HOLD·녹화 꺼짐 연결을 유지한다.
- 관제탑 PC에서 `agents/taught_return.py`, `robot/remote_client.py` 존재 확인이 False였다고 전달받았다. 그 시점 관제탑에는 새 호출 코드가 없었다. 다음 담당자는 이 브랜치 코드를 검토·반영한 후 기존 절차로 서버를 재시작해야 한다. 이미 키가 준비된 터미널은 값을 출력하지 않고 재사용할 수 있다.
- 앞선 **R1-1 모형폰 1회**는 손으로 밀거나 받치지 않고 집기·배출·홈 복귀에 성공했다고 사용자가 확인했다. 그 시험은 로봇 PC에서 API를 조회한 뒤 localhost RPC로 실행한 것으로, 아래 showcase 연동이나 관제탑 PC→로봇 PC LAN 시험과 구분한다.
- 이번 변경은 showcase가 사용하는 `POST /api/kiosk/returns` → 승인된 DB 칸 → 인증된 RPC → 티칭 11단계 → 직원 교차 검증 대기를 연결한다. 모터는 모의 드라이버로 시험했다. 실제 파지 센서 검증을 구현했다고 주장하지 않는다.

## 호출 흐름

1. 습득 접수·특징 저장·칸 배정은 기존 관제탑을 사용한다. 작업자가 그 물건을 해당 실물 칸에 놓는다.
2. 분실 신고로 후보를 선택하고 기존 동의·신분·확인 질문을 통과한다. 실물 연결 모드에서는 `/sim/lost`의 연출기도 방문/회수 버튼을 기다린다. 분실 문장만으로 자동 이동하지 않는다.
3. 실물 동작 입구는 두 개다. **회수 · 본센터 키오스크 → 물건 꺼내기**(`POST /api/kiosk/returns`)는 찾기 번호와 신분 확인값만 보낸다. **직원 확인 후 실물 로봇 실행**(`POST /api/admin/claims/{claim_id}/visit`)도 같은 반환 흐름을 호출한다. 직원 입구는 기존 관리자 인증 정책을 따르며 직원 대면 확인으로 `staff_quiz_override=true`를 보내 확인 질문을 대신할 수 있다. 현장 관문 3개가 모두 참이어야 하고 동의·본인인증은 대신하지 못한다. 브라우저가 칸·자세를 지정하지는 못한다.
4. 서비스가 찾기 요청의 물건을 확인하고 보관함 API와 같은 저장소에서 target을 만든다. 단일 반환 잠금·중복 사례·현재 상태 검사를 유지한다.
5. `agents/taught_return.py`가 기존 웹/현장 관문을 통과한 뒤 `반환 중` 기록에 성공했을 때만 `robot_run_sequence(target, progress=...)`를 호출한다. VLA/GPU 사용권은 이 티칭 경로에서 필요 없다.
6. 원격 실행부가 11단계를 실행하고 각 단계의 시작/도착 22개 사건을 돌려준다. 관제탑은 모두 순서대로 확인한다. 3·4·5초는 보간 시간이며 도착 제한 시간이 아니다.
7. 11개 도착·홈 도착을 확인하면 `인계 대기`로 기록한다. 파지·배출의 실제 성공과 최종 인계 완료는 직원이 `/staff`에서 대조한다. 가상 자동 인계는 꺼진다.
   - **11/11 바뀜(무인 인계, #208)**: 정상 흐름의 최종 인계는 분실인이 제출보관함에 물건이 놓였는지 보고 꺼낸 뒤 본센터 키오스크 [물건 받았어요](`POST /api/kiosk/handover`)로 남긴다. 물건이 없거나 다르면 분실인이 직원을 부른다. `/staff` 대조는 예외(직원 대면 확인으로 진행한 요청·직원 보관 선반 물건)에만 쓴다. 로봇 옆 정지 담당자 규칙은 그대로다
8. 실패·정지·통신 불확실은 정지 요청 후 보류한다. 전체 집기 재시도·자동 재개·가짜 로봇 성공 fallback은 없다. 이미 물건을 건드렸을 수 있으므로 원래 보관 상태로 자동 되돌리지 않는다.

직원 입구는 `/live` 처리 현황과 `/showcase` 찾기 요청 카드에 있다. 실물 모드에서 버튼에 **실물 로봇 실행**을 표시하고, 누르면 11단계 시작·대면 확인·물품 배치/경로/정지 수단 확인창을 거친다. 취소하면 요청을 보내지 않는다. 이는 조작 실수를 줄이는 표시이며 서버 관문이나 로봇 PC의 로컬 실행 허용을 대체하지 않는다. 초기 시험은 R1-1 휴대폰을 새로 접수해 진행한다. 초기 핸드크림 R3-1은 현재 허용 칸이 아니다.

팀 DB 미러의 시작 시 번호 충돌 처리는 `reset(startup=True)`를 내부적으로 호출한다. `db_mirror.attach`가 이야기 없는 초기 상태에서만 호출하며 실제 로봇을 제어하지 않는다. 일반 화면/API 초기화 차단은 유지한다.

일반 경로:

`home → pose_N → pose_N_open → pose_N_target → pose_N_close → pose_N → outlet_return_1 → close → open → outlet_return_1 → home`

7·8번은 기존 전용 return/outlet/close와 그리퍼 값을 사용한다. 기존 1·2·3·7번 하중 보정도 유지한다.

## 최신 열 배치와 티칭 확인

| 열 | 칸/자세 | 최신 main의 품목 | 이번 실물 확인 |
|---|---|---|---|
| R1 | 1·2 / pose_1·2 | 휴대폰 | 1번 이전 시험 무보조 성공, 새 연동은 미시험 |
| R2 | 3·4 / pose_3·4 | 보조배터리 | 새 품목 배치 기준 확인 필요 |
| R3 | 5·6 / pose_5·6 | 핸드크림 | 새 품목 배치 기준 확인 필요 |
| R4 | 7·8 / pose_7·8 | 카드지갑 | 새 품목 배치 기준 확인 필요 |

칸↔pose 번호는 그대로다. 접근 좌표가 같아도 타겟 높이·집게 벌림·닫힘이 새 품목에 맞는다는 보장은 없다. 이번에는 **40개 원본 자세, 7·8번 전용 그립, 하중 보정 값을 바꾸지 않았다.** 실물에서 확인한 칸만 원격 서버의 `--allow-slot`으로 허용한다. 초기 실물 연결 시험은 R1-1 하나만 허용하는 것을 권한다.

## 적용 파일과 계약

- 관제탑: `agents/taught_return.py`, `agents/sim_director.py`, `agents/service.py`, `agents/backends.py`, `agents/api.py`.
- 로봇 PC: `robot/remote_client.py`, `robot/remote_executor.py`, `robot/tower_part.py`와 기존 자세/시퀀스/보정 설정.
- 화면: `web/showcase/index.html`, `web/live/index.html`, `web/kiosk/index.html`.
- 선택 계약 `robot_run_sequence(target, progress=None)`를 추가했다. 기존 필수 함수·VLA 경로는 바꾸지 않았다. 시험 전용 `run_pose_sequence_test`도 그대로 사용 가능하다.
- 성공 결과는 `ok=true`, `test_only=false`, `motion_complete=true`, `item_id`, 정확히 11개의 `completed`를 포함한다. 이것은 파지 검증 성공이 아니다. 관제탑은 별도로 22개 진행 사건도 검사한다.
- 진행 사건: `{event: stage_started|stage_arrived, index: 1..11, total: 11, pose_name, command_pose}`. HTTP 상태는 사건 목록을 반환하고 클라이언트가 중복 전달하지 않는다.
- 사례 결과의 `robot_sequence`에는 작업 ID·칸·마지막 도착·실패 자세·직원 확인 필요가 들어간다. 기존 PostgreSQL 표에는 각 이동/도착 이름을 `return_step.step`으로 저장하므로 DB 마이그레이션은 추가하지 않았다.
- 관제/화면 파일은 로봇 폴더 밖 변경이다. PR 설명에 위 파일과 실제 도착 대기·기존 관문 유지·가상 성공 차단의 이유를 적어 관제탑 담당자가 검토하도록 한다.

## 두 PC 적용 순서 (사람이 수행)

먼저 두 PC가 **이 변경을 포함한 동일한 코드**를 받아야 한다. PR 병합 전에는 이 작업 브랜치를 사용한다. 기존 main만 pull해서는 새 호출 코드가 생기지 않는다. 관제탑 PC의 미커밋 작업을 보존하고 병합 차이를 검토한다.

Studio 서버/드라이버/티칭 JSON은 이번에 바뀌지 않았다. 기존 49개 런타임 자세·9개 보정 프로필이 설치돼 있어야 한다. Studio를 다시 설치하거나 별도 serial 연결을 열지 않는다.

### 1. 비밀값 준비

사람이 두 PC의 현재 PowerShell 환경에 동일한 `TOWER_REMOTE_ROBOT_TOKEN`을 비공개로 준비한다(32자 이상 랜덤 ASCII). 로봇 PC에는 `TOWER_STUDIO_FOLLOWER_ID`도 비공개로 준비한다. 값은 대화·명령 인자·Git에 넣지 않는다. `.env.example`에는 이름만 추가했다.

### 2. 로봇 PC (10.10.21.30)

실물 경로와 물건을 확인하고 기존 독립 시퀀스 패널(8766)을 종료한다. **Studio 연결은 유지**한다. HOLD·녹화 꺼짐이며 다른 이동·텔레는 없어야 한다.

저장소 폴더에서:

```powershell
$env:TOWER_ROBOT_MOVE_SECONDS = '5'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_executor `
  --live --host 0.0.0.0 --port 8767 --allow-client 10.10.21.21 --allow-slot R1-1
```

처음에는 DISARMED다. 다른 터미널에 같은 비밀 환경값을 준비하고 로컬 확인 후 허용:

```powershell
$env:TOWER_REMOTE_ROBOT_URL = 'http://127.0.0.1:8767'
$env:TOWER_REMOTE_ROBOT_MODE = 'live'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client status
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client arm --approved
```

허용만으로 이동하지 않는다. 다른 칸 허용은 실물 확인 후 `--allow-slot R1-2`처럼 인자를 추가해 서버를 다시 준비한다. 관제탑 PC에서 arm은 불가능하다. TCP 8767은 필요한 관제탑 IP에서만 접근하도록 한다. 이번 작업에서 방화벽은 변경하지 않았다. 공유 네트워크는 기존 원격 안내의 TLS/터널 설정을 사용한다.

### 3. 관제탑 PC (10.10.21.21)

기존 서버를 사람이 정상 종료한 뒤, 같은 터미널에 비밀 키를 준비하고:

```powershell
$env:TOWER_SIM = '1'
$env:TOWER_ROBOT_TARGET = 'db'
$env:TOWER_ROBOT_PART = 'robot.remote_client:RemoteTowerRobot'
$env:TOWER_ROBOT_SEQUENCE = 'taught'
$env:TOWER_REMOTE_ROBOT_URL = 'http://10.10.21.30:8767'
$env:TOWER_REMOTE_ROBOT_MODE = 'live'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client status
tools\start_tower.bat lan
```

`status`로 mode=live·armed=true·sequence_slots=[R1-1]을 확인한다. `start_tower.bat`는 기존 동작대로 DB 마이그레이션/개인정보 보존기간 정리도 실행하므로 관제탑 담당자가 기존 운영 절차에 따라 실행한다. `dev` 자동 재시작은 사용하지 않는다. 환경을 설정해도 서버를 재시작하지 않으면 반영되지 않는다.

`TOWER_SIM=1`은 접수/찾기 저장소가 메모리이고 팀 PostgreSQL에 미러링할 수 있다는 뜻이다. 실물 로봇은 명시적인 `TOWER_ROBOT_SEQUENCE=taught` 분기로 교체된다. **직접 PostgreSQL을 읽는 모드로 바꿨다고 표현하지 않는다.**

### 4. Showcase에서 한 바퀴

1. `/showcase?scene=found`에서 접수하고 DB가 배정한 칸을 확인한다. 실물을 그 칸에 놓는다.
2. 분실 신고에서 물건을 선택·승인하고 찾기 번호를 받는다.
3. 상단에 **실물 로봇** 표시가 있는지 확인한다. **회수** 탭에서 찾기 번호·신분 확인 후 **물건 꺼내기**를 한 번 누른다. 누르면 실물 동작이 시작된다.
4. 로봇 작업대와 단계 기록으로 1/11~11/11 도착을 확인한다. 그림은 배치 참고도이며 실시간 실물 관절값이 아니다.
5. 물건이 실제로 제출보관함에 놓였는지 보고 `/staff`에서 교차 검증 후 인계한다. (11/11부터: 정상 흐름은 분실인이 꺼내고 키오스크 [물건 받았어요], `/staff` 는 예외만) 버튼 결과는 이동 완료이며 파지/배출을 자동으로 검증했다는 뜻이 아니다.

직원 대면 확인으로 진행하는 경우에는 `/live` 또는 `/showcase` 찾기 요청 카드의 **직원 확인 후 실물 로봇 실행**을 사용할 수 있다. 이 버튼도 실제 같은 11단계를 시작하므로 회수 버튼과 중복으로 누르지 않는다. 이동 완료 후 직원의 최종 교차 검증·인계는 그대로 필요하다.

## 정지·실패

- 키오스크 정지 또는 `/api/robot/stop`은 기존 관제탑 정지 입구를 통해 같은 원격 부품을 정지시킨다. 원격 lease 5초 단절도 정지 요청·실행 불허로 전환한다. HOLD는 하드웨어 비상정지가 아니다.
- 결과가 끊겨도 브라우저에서 다시 누르지 않는다. 로봇 PC에서 실제 위치·물건·정지 상태를 먼저 확인한다. 작업 자동 재전송/자동 재개는 없다.
- 정지 후 로컬 재허용은 원격 실행부의 새 epoch를 만든다. 관제탑의 기존 정지 잠금도 별도이므로 **로컬 arm만으로 관제탑 정지까지 해제되지 않는다.** 현재 `robot_home`은 미구현 실패를 유지한다. 운영자의 원복/상태 점검 후 관제탑 복구 절차가 필요하며 가짜 home 성공으로 해제하지 않는다.
- 실물 연결 중 가상 초기화 버튼은 숨기고 API도 거절한다. 메모리 기록만 초기화해 실물과 어긋나는 것을 막는다.

## 검증

직원 입구 후속 보완 기준: Windows 전체 unittest **1,486개 실행·1,457개 통과·29개 skip·실패 0개**. 직원 입구/시작 시 재정렬 관련 13개 시험과 두 화면 JavaScript 구문 검사도 통과했다. 두 직원 버튼의 실제 핸들러를 DOM/요청 대역에서 실행해 확인창 취소 시 요청 0회, 승인 시 1회를 확인했다. 이것은 브라우저 실물 시연을 대신하지 않는다.

최종 공유 전 main `9bab15a`까지 통합했고 전체 시험 **1,483개 실행·1,454개 통과·29개 skip·실패 0개**를 확인했다. 상태 응답 충돌은 실물 모드 표시와 팀원 측 찾기 요청 목록을 모두 유지해 해결했다. 아래 시험은 모의 드라이버이며 실물 완료 신호를 검증했다는 뜻이 아니다.

`tests/test_taught_return.py`: showcase와 같은 회수 API, 실제 loopback HTTP 인증/작업 조회, 모의 모터 사용. 8칸 22개 진행 사건, 마지막 도착 대기, 직원 확인 대기, 중복/신분 불일치/화면 칸 주입 차단, 미허용 칸, 중간 실패/정지, 가상 자동 인계 차단, 근거 없는 ok 응답 거절을 확인한다.

직원 visit API도 같은 모의 RPC/모터로 검사한다. 확인 질문 미통과 요청은 키오스크에서 막히고, 인증 없는 직원 호출은 움직이지 않으며, 인증된 대면 확인 경로는 11단계 후 직원 확인 대기로 끝난다. 같은 직원 요청 재실행은 거절되고 DISARMED 실행부는 가상 성공으로 대체하지 않는다. `tests/test_claim_cancel_visit.py StartupReseedTest`로 시작 시 재정렬 허용/일반 초기화 차단도 확인한다.

`tests/test_remote_robot.py`: 기존 lease·중복·지연 요청·미확인 정지에 더해 준비 중 정지 신호를 지우지 않는 검사를 포함한다. 전체 시험 결과는 로컬 `outputs/robot_db_check/showcase-taught-full-tests.txt`에 남긴다.

남은 실물 검증: 실제 관제탑 PC→로봇 PC 통신, showcase 클릭, 변경 품목의 2~8번 경로와 파지, 장시간 반복, 네트워크 단절 시 현장 HOLD. 사람이 로봇 옆에서 경로·정지 수단을 확인하고 시작한다.
