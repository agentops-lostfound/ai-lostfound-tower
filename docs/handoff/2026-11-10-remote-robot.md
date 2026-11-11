# 두 PC 원격 로봇 실행부 · LF-21

> 11/10 마감: 로봇 PC LIVE 서버는 DISARMED로 대기 중이며, 사용자가 관제탑 PC에서 인증된 상태 조회 성공을 전달했다. 관제탑 호출 코드는 관제탑 PC에 미반영 상태였다. 새 실행/도착/완료 실물 시험은 아직 하지 않았다. 이 후속 구현은 사용자 요청으로 기존 브랜치에 커밋·푸시·PR 공유하며, 아래 '미커밋·미푸시' 및 '두 PC 상태 조회 미실행' 문구는 이전 이력이다. [오늘 결과와 다음 담당자 순서](../reports/2026-11-10-remote-robot-update.md)를 우선 참고한다.

> 후속 로컬 구현: [showcase 회수 버튼 → 원격 티칭](2026-11-10-showcase-taught-robot.md)을 추가했다. `TOWER_ROBOT_SEQUENCE=taught`를 명시하면 별도 운영 진입점 `robot_run_sequence`로 11단계를 호출하고 진행/도착을 기다린다. 기존 필수 grasp/verify/deliver/home의 미구현 응답을 성공으로 바꾸지 않았다. 아래의 '운영 연결 미구현'은 이전 이력이며, 새 코드도 두 PC 배포·새 실물 시험은 아직 하지 않았다.

> 사용자 확인 완료: 아래 1번 실물 시험에서 **손으로 밀거나 받치는 보조 없이 모형폰 집기·배출구 놓기·홈 복귀 모두 성공**했다고 명시적으로 확인했다. `user-confirmation.json`과 결과 JSON에 기록했다. 한 번의 R1-1 시험에 대한 실물 확인이며 다른 칸, 관제탑 PC→로봇 PC LAN 송신, showcase 회수 버튼 연동까지 검증한 것은 아니다. 아래의 사용자 확인 대기 문구는 이전 상태다.

> 후속 실제 시험: 사용자가 1번 R1-1 모형폰·전체 경로·정지 수단을 확인한 뒤, 로봇 PC가 관제탑 보관칸 API에서 `H-20261110-0001 → R1-1 → pose_1`을 조회하고 localhost 원격 실행부를 통해 실물 11단계를 1회 실행했다. 11개 도착 응답·home 복귀, 이동 구간 약 65.96초, 결과 `ok=true`, DB 쓰기 0건. 기록은 `outputs/robot_db_check/actual-db-trial-20261110-150113/`다. 파지·배출의 실물 성공과 수동 보조 유무는 사용자 확인 대기이며, 이 시험은 관제탑 PC 송신이나 showcase 버튼 연동 시험이 아니다. 현재 showcase는 `sim=true`, 판정 저장소 memory, 팀 DB 미러 연결 상태다. 본문의 실물 미실행 기록은 이 시험 이전 이력이며 두 PC LAN·운영 연결 미실행은 여전히 유효하다. 임시 실행 서버는 종료했고 기존 8766 패널과 수신 연결을 복원했다.

관제탑 `10.10.21.21:8100`은 유지하고, Studio·팔이 연결된 `10.10.21.30`에서 명령을 실행한다. 기존 브랜치 `LF-21-geontae-tower-robot-part`에서 개발했다. 이 후속 변경은 아직 커밋·푸시하지 않았다.

```mermaid
flowchart LR
    A[관제탑 10.10.21.21\n매칭·승인·DB 칸 조회] --> B[RemoteTowerRobot\nHTTP 작업·heartbeat·정지]
    B --> C[로봇 PC 10.10.21.30:8767\n로컬 실행 허용·단일 작업]
    C --> D[TowerRobot\n기존 Studio IPC]
    D --> E[티칭 11단계·기존 하중 보정]
```

## 구현 범위

- `robot/remote_executor.py`: 인증·발신 IP 제한, 시작 시 실행 불허, 로봇 PC의 loopback 요청으로만 허용, 작업 상태 조회, 단일 작업, 중복 ID 재실행 방지, 제어 lease와 정지.
- `robot/remote_client.py`: 관제탑용 표준 라이브러리 클라이언트. import·생성만으로 연결하지 않는다. `robot_go_pose`와 필수 함수 6개를 제공하며, `run_pose_sequence_test(target)`로 기존 11단계 시험 전체를 원격 실행한다. 관제탑 PC에는 torch·LeRobot·WSL이 필요 없다.
- 원본 티칭과 1·2·3·7번 보정, 7·8번 전용 그리퍼는 기존 실행부를 재사용한다. 임의 관절값·serial 명령·모듈 이름을 HTTP로 받지 않는다.
- 원격 서버의 각 작업은 같은 `TowerRobot` 인스턴스를 사용한다. 재허용하면 새 인스턴스를 만들고 제어 epoch를 교체한다. 이전 epoch의 늦은 요청은 거부한다. 작업 기록은 프로세스 메모리에 보관하며 서버 재시작 후 복구·자동 재개하지 않는다.

**아직 운영 반환 완료 연결은 아니다.** 기존 `TowerRobot.robot_grasp/verify_grasp/deliver/home`의 미구현 실패 응답을 그대로 전달한다. 원격 통로가 생겼다고 이 함수를 성공 처리하지 않는다. 현재 끝까지 움직이는 진입점은 명시적인 **11단계 시험 명령**이다. 실제 파지·전달을 판정하거나 DB 상태를 바꾸지 않는다. `robot_state`는 normalized→계약 각도 변환이 미확정이라 미제공으로 처리하고, 가짜 관절 상태로 fallback하지 않는다. 원격 작업 상태는 `health`·작업 조회로 본다.

## 설정 이름

실제 키·Follower 값은 문서·대화·커밋에 적지 않는다. `.env`는 AI가 읽거나 편집하지 않는다. 아래 명령은 **현재 터미널의 OS 환경변수**만 사용하며 `.env`를 자동으로 읽지 않는다.

| 이름 | 설정 위치·의미 |
|---|---|
| `TOWER_REMOTE_ROBOT_TOKEN` | 두 PC에 비공개로 같은 32자 이상 랜덤 ASCII 키를 준비. URL·명령 인자에 넣지 않음 |
| `TOWER_REMOTE_ROBOT_URL` | 관제탑은 `http://10.10.21.30:8767`, 로봇 PC 로컬 허용 터미널은 `http://127.0.0.1:8767` |
| `TOWER_REMOTE_ROBOT_MODE` | 실물 `live`, 모의 시험만 `simulation`. 서로 다르면 실행 거부 |
| `TOWER_STUDIO_FOLLOWER_ID` | 로봇 PC에 등록된 실제 Follower ID. 사람이 비공개로 설정 |
| `TOWER_STUDIO_CONTAINER`, `TOWER_STUDIO_DISTRIBUTION` | 로봇 PC의 기존 Studio/WSL 이름. 비우기보다 줄 생략 또는 실제 기본값 설정 |
| `TOWER_ROBOT_MOVE_SECONDS` | 로봇 PC에서 3·4·5, 보간 시간이며 도착 제한 시간이 아님 |
| `TOWER_ROBOT_PART` | 관제탑 부품 경로 `robot.remote_client:RemoteTowerRobot` |
| `TOWER_ROBOT_TARGET` | 관제탑 DB 칸 방식 `db` |

HTTP 예시는 통제된 실험망용이다. 공유망에서는 TLS 또는 암호화 터널을 사용한다. 서버는 `--tls-cert`·`--tls-key`를 지원하고 클라이언트는 HTTPS 인증서를 정상 검증한다. 인증키를 로그나 메신저로 전달하지 않는다. 필요한 네트워크 허용은 관제탑 IP→로봇 PC TCP 8767로 한정한다. 이 작업에서는 방화벽 정책을 변경하지 않았다.

## 1. 먼저 모의 통신 시험

로봇 PC 저장소 폴더에서, 키 환경변수를 비공개로 준비한 뒤 첫 터미널:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_executor --host 127.0.0.1 --port 8767
```

기본은 SIMULATION·DISARMED다. 다른 터미널에 같은 키를 준비하고:

```powershell
$env:TOWER_REMOTE_ROBOT_URL = 'http://127.0.0.1:8767'
$env:TOWER_REMOTE_ROBOT_MODE = 'simulation'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client status
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client arm --approved
```

아래 시험 명령은 먼저 관제탑에서 물건 ID의 DB 칸을 읽고, 그 target을 모의 서버로 보낸다. 예시 ID는 실제 승인된 시험 물건 번호로 바꾼다. 이 단계 서버에는 `--live`를 넣지 않는다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client sequence --tower http://10.10.21.21:8100 --item-id '승인된_시험_물건번호' --approved
```

## 2. 실물 서버 준비 — 현재는 실행하지 않음

기존 49개 자세·9개 프로필 설치와 실제 경로 검증이 선행 조건이다. 물건을 내려놓고 기존 시퀀스 패널(8766)을 종료한다. Studio의 연결은 유지하고 HOLD·녹화 꺼짐 상태로 둔다. 다른 창에서 이동·텔레를 동시에 실행하지 않는다.

로봇 PC 첫 터미널(키·Follower 환경변수 준비):

```powershell
$env:TOWER_ROBOT_MOVE_SECONDS = '5'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_executor --live --host 0.0.0.0 --port 8767 --allow-client 10.10.21.21
```

서버를 켜는 것만으로 로봇에 연결하거나 움직이지 않는다. 로봇 PC의 다른 터미널에서 URL을 loopback, mode를 live로 설정한 뒤 경로·정지 수단을 확인하고 로컬 실행 허용:

```powershell
$env:TOWER_REMOTE_ROBOT_URL = 'http://127.0.0.1:8767'
$env:TOWER_REMOTE_ROBOT_MODE = 'live'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client arm --approved
```

허용 시 Studio의 기존 IPC에서 신선한 관측·HOLD·녹화 꺼짐을 확인한다. 시퀀스 패널이 켜져 있거나 다른 저장 자세가 진행 중이면 거부한다. 별도 serial 연결이나 Studio 재시작은 하지 않는다. 관제탑 IP에서 보내는 arm 요청은 키가 맞아도 거부한다.

## 3. 관제탑 PC

사람이 OS 환경변수 또는 관제탑의 기존 비밀값 관리 방식으로 같은 키를 준비한다. URL은 로봇 PC 주소, mode는 live다. 상태 확인은 이동하지 않는다:

```powershell
$env:TOWER_REMOTE_ROBOT_URL = 'http://10.10.21.30:8767'
$env:TOWER_REMOTE_ROBOT_MODE = 'live'
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client status
```

**실물 서버에서 아래 명령은 실제 11단계 이동을 시작한다.** 사람이 로봇 옆에서 경로·정지 수단을 확인하고 실행을 승인했을 때만 사용한다. 실제 물건을 분실인에게 인계 완료로 기록하는 명령은 아니다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client sequence --tower http://10.10.21.21:8100 --item-id '승인된_시험_물건번호' --approved
.\.venv\Scripts\python.exe -X utf8 -m robot.remote_client stop
```

## 관제탑 담당자 연결 지점

- 일반 부품 모드는 `TOWER_ROBOT_PART=robot.remote_client:RemoteTowerRobot`, `TOWER_ROBOT_TARGET=db`로 사용한다. 부품 객체는 한 번 만들어 공유한다.
- 현재 `agents/api.py`의 `TOWER_SIM=1` 분기는 외부 부품을 읽기 전에 반환한다. **설정만 넣으면 가상 시연에서 실물로 바뀐다고 가정하지 않는다.** 관제탑 담당자가 명시적인 실물 활성화 분기를 연결해야 한다. 이번 작업에서는 이 운영 코드를 변경하지 않았다.
- 서버가 DB에서 승인·선택한 target을 얻은 **별도 승인된 시험 경로**에서 `remote.run_pose_sequence_test(target)`를 호출하면 전체 11단계를 실행하고 결과를 기다린다. 외부 브라우저가 보낸 임의 slot을 그대로 사용하지 않는다. 클라이언트는 DB를 갱신하지 않는다.
- 기존 supervisor의 단계별 grasp·파지 검증·deliver 연결은 후속 작업이다. 센서나 직원 확인을 어떻게 받을지 정한 뒤 연결한다. 시험 성공을 파지 성공이나 DB 반환 완료로 치환하지 않는다.

## 실패·정지 동작

- 단일 작업만 허용한다. 같은 ID·같은 내용의 POST는 기존 결과만 반환하며 다른 내용으로 같은 ID를 쓰면 거부한다. 기록 최대 1,024건 뒤에는 로컬 점검·재시작이 필요하다.
- 클라이언트는 작업 동안 heartbeat를 보낸다. 5초 이상 끊기면 실행 서버가 취소·정지를 요청하고 실행 허용을 해제한다. 3·4·5초 이동 시간이 지났다고 실패시키거나 다음 단계로 넘기지 않는다.
- 응답을 못 받으면 클라이언트는 새 ID로 재전송하지 않는다. 정지 요청을 하고 실패를 반환한다. 정지가 작업 등록보다 먼저 도착해도 해당 ID를 차단한다. 재시작·재허용 전의 늦은 요청도 epoch 검사로 차단한다.
- 실패 후에는 로봇 PC에서 상태·경로를 확인하고 다시 로컬 허용한다. 정지 미확인이면 재허용도 거부한다. Studio 상태 응답은 하드웨어 비상정지 보장이 아니다. 실행 서버/PC 자체 장애와 다중 Studio 클라이언트 동시 조작은 별도 한계이며 실물 정지 수단이 필요하다.

## 검증·미실행 사항

모의 HTTP로 중복 실행, busy, 잘못된 칸, 미승인, 통신 lease, 정지 선행 경합, 정지 미확인, 오래된 epoch, 원격 arm 거부, 모의/실물 혼동, Ctrl+C 정지를 검증했다. 원격 전용 시험은 17개다. 8개 칸의 실제 티칭 파일 기반 11단계 모의 실행을 검사하고, 실제 관제탑의 물품 5건 응답도 localhost HTTP 서버→모의 모터로 통과했다. 물리 명령과 DB 쓰기는 0건이다.

최종 전체 unittest는 **1,408개 실행·1,382개 통과·26개 skip·실패 0개**다. 시험 기록은 로컬 `outputs/robot_db_check/remote-executor-full-tests.txt`, 실제 DB 응답 기반 모의 HTTP 결과는 `remote-executor-db-http-smoke.json`에 있다. 관제탑용 클라이언트는 `python -S`에서도 import와 필수 함수 검사를 통과해 외부 패키지 의존성이 없음을 확인했다.

아직 관제탑 PC에서 로봇 PC로 접속한 LAN 시험, 실물 서버 기동·로컬 실행 허용·실제 이동, 관제탑 운영 설정·코드 변경, 커밋·푸시는 하지 않았다. 키는 생성·공유하지 않았고 Studio·기존 시퀀스 패널과 방화벽은 변경하지 않았다. Windows PowerShell에서 부품 import만 확인할 수 있다:

```powershell
.\.venv\Scripts\python.exe -c "from agents.robot_part import load_robot_part; from agents.robot_api import check_robot_part; print(check_robot_part(load_robot_part('robot.remote_client:RemoteTowerRobot')))"
```
