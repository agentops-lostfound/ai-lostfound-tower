# LF-12 소유자 패치 적용 및 복원 준비

2026-11-04. 기존 a4add9deceb34f9ea9289c8843dc8aa9 후보와 보정값을 그대로 이어서 사용한다. 사용자 컨테이너 Zenoh 1.9.0에서 가짜 장비 통신 5개 시나리오가 통과했다. 재보정이나 패치 후보 재생성은 필요 없다.

## 완료 및 남은 범위

- 보정 복원/readback, 두 팔 기준 일치, 토크 OFF, Windows 백업: 사용자 확인 완료.
- 후보 소유자 루프 4개 모의 시험, 실제 Zenoh + 가짜 장비 통신 5개 시나리오: 완료.
- 새 적용/복원 도구: 원본 해시 확인, 활성 소유자/세션/USB 사용 시 변경 중단, 원본과 후보 영구 볼륨 백업, Windows 사본 해시 검증, 원자적 파일 교체, 부분 실패 시 원본 복구, 알 수 없는 변경 보존.
- 조작 화면: 상태와 정지만 제공. 별도 지속 통신 작업자로 상태 조회가 정지 전송을 막지 않도록 구성. 현재 소유자 세션에만 정지를 요청하며 새 소유자나 토크를 자동 시작하지 않는다. 통신 장애 시 마지막 관측 세션에 대한 정지 재시도 버튼은 유지한다. 페이지나 터미널 종료는 정지 명령이 아니다.
- 실물 정지·Home·정지 지연·충돌 회피·연결 실패 시 토크 상태는 아직 미검증. 초기 실물 시험에서 이동/재개/Home을 제공하지 않는다.

## 기존 후보로 적용 준비

VS Code PowerShell, 팀 저장소 pil2ya에서 실행한다.

```powershell
git pull --ff-only origin pil2ya
$ownerTrial = py -3.11 .\tools\prepare_robot_owner_trial.py prepare --candidate-dir ".\outputs\robot-owner-patch\a4add9deceb34f9ea9289c8843dc8aa9" | ConvertFrom-Json
$ownerTrial | Format-List
```

READY_FOR_APPLY이면 컨테이너에 원본 코드와 후보가 백업됐고 Windows 사본까지 검증된 것이다. 이 단계에서 설치 파일은 바뀌지 않는다. 실패 시 강제 적용하거나 모터 설정을 바꾸지 않는다.

## 적용과 화면 준비 (하드웨어 연결 없음)

Studio 연결 해제 및 토크 OFF 상태를 유지한다. 다음 명령은 설치 코드만 바꾸며 재시작/장비 연결/토크 ON을 수행하지 않는다. 패치된 대상 팔로워는 기존 Studio Teleoperate/policy 명령을 폐기하므로 이전 기능과의 호환을 가정하지 않는다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py apply --trial $ownerTrial.trial_file
py -3.11 .\tools\prepare_robot_owner_trial.py panel --trial $ownerTrial.trial_file
```

PATCH_INSTALLED_NO_HARDWARE_CONNECTION 뒤 화면 실행 안내가 나오면 브라우저에서 http://127.0.0.1:8770 을 연다. 소유자가 없는 현재 상태의 정상 표시는 ‘전용 소유자 응답 없음. 장비를 자동 연결하지 않습니다.’이다. 패널을 띄운 것만으로 Studio를 연결하지 않는다. 실물 연결은 사용자가 보는 화면·받침·주변 공간 및 시작 시 드라이버의 토크 설정/현재 위치 목표 정렬을 확인하는 후속 단계다.

원본/후보 백업은 Windows outputs/robot-owner-trial/<ID>/backup과 컨테이너 /app/storage/patches/lf-owner-safety-<ID>에 있다. trial.json은 Windows 경로와 컨테이너 경로를 기록한다. outputs는 Git에 올리지 않는다. 컨테이너 재생성으로 /tmp 시험 도구가 사라졌으면 기존 trial 명령이 실패할 수 있으며 설치 상태를 확인한 뒤 복구한다.

## 원본 코드로 되돌리기

1. 조작 화면 서버를 실행한 터미널에서 Ctrl+C로 종료한다. 이것만으로 로봇이 정지하는 것은 아니다.
2. 실물 연결 후라면 조작 화면에서 정지 처리 확인 → Studio 세션 종료 → UI 통신 작업자 종료 → USB 소유 프로세스 해제를 먼저 확인한다. 단순 runtime stop이나 화면 OFF를 물리 정지로 간주하지 않는다.
3. 같은 PowerShell에 $ownerTrial이 남아 있으면 다음을 실행한다. 새 터미널이면 Windows outputs/robot-owner-trial/<ID>/trial.json의 실제 경로를 --trial에 지정한다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py rollback --trial $ownerTrial.trial_file
```

ORIGINAL_RESTORED_NO_HARDWARE_CONNECTION이면 코드가 원래 바이트로 복원됐다. 활성 프로세스나 알 수 없는 파일 변경이 있으면 도구가 중단하므로 강제 삭제하지 않는다. 코드 복원은 모터의 토크 해제나 보정 복원이 아니다.

## 검증 기록

클라우드: 전체 144개 시험 실행, 2개 건너뜀. 임시 설치 폴더에서 적용/복원 왕복, 부분 디스크 실패의 원본 복구, 알 수 없는 변경 보존, 활성 소유자 차단 시험 통과. HTTP 화면의 명령 없는 로드, 상태/정지 작업자 분리, 잘못된 요청 차단, 관측한 세션에만 정지 요청, 이동/재개/Home 경로 부재 시험 통과. Zenoh 1.10.2의 가짜 소유자와 실제 패널 stdin 작업자 두 개 간 상태·정지·유지 완료·재개 거부도 확인했다. Windows Docker 실행 래퍼 및 실물 드라이버는 사용자 환경에서 후속 확인한다.

## 백업 준비의 /proc 권한 오류 후속

사용자 환경에서 prepare의 backup 전 require_idle이 /proc/1403/fd PermissionError로 중단됐다. 백업 함수는 idle 확인을 첫 단계로 수행하므로 이 실패에서는 원본 백업/설치 파일 변경/적용 가능한 trial.json 생성이 이루어지지 않았다. 복사된 임시 시험 도구와 기존 후보는 그대로 보존한다.

관리 작업(check/backup/apply/rollback)만 docker exec --user 0으로 실행하도록 수정했다. 장비 통신·화면 작업자는 기존 사용자로 실행한다. 관리자 권한으로 파일을 교체할 때 기존 소유 UID/GID와 접근 모드를 유지한다. 읽을 수 없는 프로세스를 건너뛰거나 --privileged를 사용하지 않는다. 관리자 실행 후에도 프로세스 정보가 제한되면 검사 EUID와 대상 UID를 표시하고 중단한다. 기존 후보를 다시 만들거나 보정하지 않고 git pull 뒤 실패한 prepare 단계만 재시도한다. READY_FOR_APPLY 이후의 적용·화면 명령은 위와 같다.
