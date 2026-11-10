# 2026-11-10 원격 티칭 로봇·관제탑 연결 마감 — LF-21

## 오늘 구현

관제탑은 팀장 PC에 유지하고, 로봇 PC의 기존 Physical AI Studio 연결로 티칭 시퀀스를 실행한다. VLA는 사용하지 않는다. 선택된 물품의 DB 칸으로 시작하며 기본 경로는 다음과 같다.

`home → pose_N → pose_N_open → pose_N_target → pose_N_close → pose_N 복귀 → outlet_return_1 → close → open → outlet_return_1 → home`

- 8칸의 기존 티칭 11단계, 7·8번 전용 그리퍼/복귀, 1·2·3·7번 하중 보정을 재사용했다. 이번 후속 연결에서 원본 40개 자세나 보정값은 바꾸지 않았다.
- `robot/remote_executor.py`: 인증·발신 IP 제한·로컬 실행 허용·칸 허용 목록·단일 작업·중복 방지·heartbeat 만료 정지·epoch로 지연 요청 차단. 서버는 기본 실행 불허로 켜진다.
- `robot/remote_client.py`: 관제탑용 표준 라이브러리 클라이언트. 시작 요청 접수, 실행 중 상태, 각 단계 시작/도착, 완료/실패/정지 응답을 조회한다. 애매한 전송은 자동 재시도하지 않는다. 준비 중 정지 신호를 지우던 경합도 방지한다.
- `robot/tower_part.py`: 운영 선택 함수 `robot_run_sequence(target, progress=None)`와 시험 진입점이 같은 티칭 실행부를 사용한다. 기존 Studio IPC 연결만 사용하며 별도 serial 연결은 열지 않는다.
- `agents/taught_return.py`: 기존 승인/신분/확인 질문 관문과 DB 상태 기록을 유지한다. 서버가 선택한 target만 사용하며 22개 진행 사건과 11개 도착·홈 복귀를 확인한 후 직원 확인 대기로 보낸다. 자동 파지 성공 판정은 하지 않는다.
- `agents/api.py`, `agents/backends.py`, `agents/service.py`, `agents/sim_director.py`: 선택 모드에서 실제 원격 부품을 꽂고 새 동작도 정지 보호에 포함한다. 가짜 로봇 성공 fallback·가상 자동 인계·실물 모드의 가상 초기화를 차단한다.
- `web/showcase/index.html`, `web/live/index.html`, `web/kiosk/index.html`: 실물 모드 표시, 단계 기록, 이동 완료 후 직원 확인 안내. 가상 관절값을 실물 텔레메트리로 표시하지 않는다.

선택 설정은 `TOWER_ROBOT_SEQUENCE=taught`, `TOWER_ROBOT_TARGET=db`, `TOWER_ROBOT_PART=robot.remote_client:RemoteTowerRobot`다. 필수 로봇 함수 계약은 유지하며 선택 함수만 추가했다. 관제탑의 LeRobot/torch 설치는 필요 없다. 계약·폴더 밖 변경 이유는 PR에 함께 적는다.

## 확인한 것과 확인하지 않은 것

| 구간 | 확인 결과 |
|---|---|
| 이전 R1-1 모형폰 실물 1회 | 로봇 PC가 보관칸 API 조회 → localhost RPC → 11단계. 약 65.96초, 사용자 무보조 집기·배출·홈 복귀 성공 확인 |
| Showcase와 같은 회수 API → RPC → 모의 모터 | 승인·DB 칸·11단계·직원 확인 대기, 8칸 사건 순서, 중복/실패/정지 차단 시험 통과 |
| 팀장 PC → 로봇 PC TCP | 사용자 접속 성공 확인 |
| 팀장 PC → 로봇 PC 인증 상태 조회 | 사용자가 `/v1/health` LIVE·DISARMED·작업 없음·미확인 정지 없음·R1-1 응답 확인 |
| 실제 두 PC 실행 요청 → 실물 완료 응답 | 미시험 |
| 팀장 관제탑 showcase 회수 버튼 → 실물 | 코드 미반영으로 미시험 |
| 새 열 배치의 나머지 칸·품목 실물 반복 | 미시험 |

현재 접수/판정은 `TOWER_SIM=1`의 메모리 저장소이며 팀 PostgreSQL로 미러링할 수 있다. 직접 PostgreSQL 읽기 기반 운영으로 전환했다고 표현하지 않는다. 관제탑이 수신 결과를 기록하며 로봇 서버는 DB를 직접 수정하지 않는다.

## 공유·현장 상태

- 같은 작업 브랜치 `LF-21-geontae-tower-robot-part`를 사용한다. 앞선 작업이 main에 병합되며 원격 브랜치가 삭제돼 있어 같은 이름으로 다시 공유한다. 새 이름의 브랜치는 만들지 않는다.
- `.env`, 연결키, Windows DPAPI 자격 파일, PID/개인 설치 정보, 사진, 백업, 임시 ZIP/패치는 커밋하지 않는다. 공유 대상은 소스·시험·설정 이름·문서다.
- 로컬 LIVE 실행 서버는 실행 불허 상태이며 로봇 동작은 보내지 않았다. Studio HOLD·녹화 꺼짐·기존 GUI 연결은 유지한다. 관제탑 재시작/DB 쓰기/방화벽 변경은 하지 않았다.
- Windows 방화벽 규칙 조회는 OS 권한으로 거부됐지만, 이후 사용자가 팀장 PC의 TCP 및 인증 상태 조회 성공을 확인했다.
- 기존 백업 `run_vision_adapter_full.py.pre_unify.bak`는 보존한다.

## 다음 담당자가 할 일

1. 팀장 PC의 미커밋 작업을 보존하고 이 브랜치를 검토·통합한다. 기존 main만 pull하면 새 원격 코드가 생기지 않을 수 있다.
2. 팀장 PC에서 전체 시험을 돌린다. 같은 비밀 키를 비공개 환경변수로 사용하고 `.env` 값은 메시지나 Git에 올리지 않는다.
3. [두 PC 적용 안내](../handoff/2026-11-10-showcase-taught-robot.md)의 환경값으로 관제탑을 정상 재시작한다. 자동 reload는 사용하지 않는다.
4. 실물·경로·정지 수단을 현장에서 확인하고 독립 시퀀스 GUI를 종료한 뒤 로봇 PC에서 로컬 실행 허용한다. Studio 연결은 유지한다.
5. 처음에는 R1-1만 허용하고 showcase 회수 버튼으로 1회 시험한다. 집기·배출·홈 복귀를 사람이 확인하고 직원 교차 검증 후 인계한다.
6. 새 배치(R1 폰, R2 보조배터리, R3 핸드크림, R4 카드지갑)의 타겟 높이/그립/보정 적합성과 나머지 칸을 확인한다.

운영 완료로 닫지 않는다. 실제 두 PC 전체 동작·실패 복구·반복 실물 검증이 남아 LF-21은 진행 중으로 유지한다.
