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

## 기존 적용 상태에서 실물 연결 직전 점검

사용자가 패치 적용·정지 화면 정상 표시를 보고했다. 새 후보를 만들거나 기존 시험을 반복하지 않는다. 원본 SO101 connect는 _configure_servos 다음 _set_torque(enabled=True)를 호출하며 그 전에 현재 위치로 목표를 갱신하지 않는다. 보정 offset 복원 후 남은 목표값으로 움직일 가능성을 줄이기 위해 토크 OFF 상태에서 현재 raw 위치와 Goal_Position을 확인하고 맞추는 준비 절차를 추가했다. 원본 드라이버/기존 정지 후보는 바꾸지 않는다.

새 VS Code PowerShell에서 기존 trial.json의 경로를 지정해 다음을 실행한다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py preflight --trial "기존 trial.json 전체 경로"
py -3.11 .\tools\prepare_robot_owner_trial.py preflight --trial "기존 trial.json 전체 경로" --sync-goal
```

기본 최종 보정 파일은 저장소 옆 soarm-setup/new-follower-calibration-complete.json이다. 다른 위치면 --expected-file로 명시한다. 첫 명령은 읽기만 수행한다. 두 번째는 소유 프로세스가 없고 6관절 토크가 OFF·위치제어 모드이며 보정값이 일치할 때만 변경 전 상태를 영구 백업한 뒤 현재 raw 위치를 Goal_Position에 기록한다. 토크·보정은 쓰지 않는다. 쓰기 후 raw 목표 일치, 토크 OFF, 현재 위치와 목표 간 최대 5 tick 이내의 자세 안정성을 확인한다. 5 tick은 준비 중 자세 변화 검출 기준이며 충돌 회피나 기계 안전 범위가 아니다.

GOAL_SYNCED_TORQUE_OFF이면 목표값 정렬만 완료된 것이다. 이후 팔을 움직이면 목표값과 다시 어긋날 수 있다. 드라이버의 연결 중 설정·토크 변경을 검증한 것은 아니므로 바로 Studio에 연결하지 않고 받침·빈 집게·사용자가 보는 정지 화면을 확인한 후 제한된 실물 연결 단계로 진행한다. 오류가 나면 자동 복원·토크 ON 없이 중단하며 백업은 유지한다.

## 현재 연결을 유지한 제한 이동 중 정지 시험

사용자는 실물 연결 후 정지 화면에서 버튼을 두 번 눌러 명령 세대 2 및 ‘정지 요청 상태 · 유지 명령 전송 완료’를 확인했다. 실제 팔이 움직이지 않고 집게가 비어 있음을 추가 확인했다. 이것은 연결/정지 요청 전달/유지 목표 전송 확인이며 이동 중 정지 검증은 아니다.

기존 패치와 Studio 연결, 정지 화면을 그대로 유지한다. 새 후보·재보정·재설치는 하지 않는다. tools/robot_bounded_stop_trial.py는 현재 소유자의 전용 통신을 사용하고 새 소유자·토크 ON·보정·Home은 시작하지 않는다. --confirm-ready 없이 재개/이동을 요청하지 않는다.

도구는 정지 및 유지 완료 상태에서 3초 카운트다운 후 맨 아래 좌우 회전(shoulder_pan)만 현재 위치 대비 최대 +1.0 정규화 단위로 약 3초간 나누어 이동한다. 정규화 1단위는 1도가 아니다. 베이스 고정·빈 집게·빈 이동 공간·보이는 정지 버튼이 전제다. 카운트다운 중 버튼을 누르면 이동을 취소한다. 이동 시작 후 버튼을 눌러야 이동 중 정지 관문을 시험할 수 있다.

도구는 세션/세대 변경·상태 지연·정규화 범위 이탈·다른 관절의 1단위 초과 변화·맨 아래 회전의 시작 대비 1.5단위 초과 변화 시 중단하고 종료 정지를 시도한다. 이 기준들은 모의 시험을 위한 제한이며 실물 충돌 회피나 최악 정지 시간 보장이 아니다. 통신 실패 시 종료 정지 전달도 실패할 수 있다. 정상 종료/예외/Ctrl+C에서 같은 소유자 세션에 종료 정지를 시도하고 자동 원점 복귀는 하지 않는다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py move-test --trial "$trialFile" --confirm-ready
```

카운트다운 뒤 ‘이동 시작’이 나오면 빨간 정지 버튼을 누른다. MANUAL_STOP_OBSERVED는 시험 중 외부 정지 래치를 관측했다는 뜻이고, hold_commanded_after_trial은 유지 명령 처리 확인이다. post_stop_span_normalized는 정지 후 약 0.5초간 소유자 관절 관측값 변화 범위다. 물리적 정지 여부는 실제 팔의 동작과 함께 확인한다. MANUAL_STOP_NOT_OBSERVED는 외부 정지를 관측하기 전에 제한 경로를 끝냈다는 뜻이며 수동 정지 시험 통과가 아니다. 종료 정지 요청 때문에 명령 세대는 버튼 클릭 외에도 증가할 수 있다.

이 코드는 모델 추론 중 정지·전체 반환 경로·Home을 시험하지 않는다. 클라우드 모의 시험 6개와 실제 Zenoh 1.10.2/제공된 상태 codec/가짜 소유자를 사용한 제한 이동 및 외부 정지 시험이 통과했다. 실제 하드웨어 이동 중 정지 결과는 아직 사용자 실행 전이다.

## 제한 이동 정지 후 Home 후보 기록

사용자의 첫 유효 실물 결과: MANUAL_STOP_OBSERVED, 최대 60개 중 51개 목표 전송, 최대 관측 변화 약 0.517 정규화 단위, 유지 명령 완료, 정지 후 관측 구간 6관절 변화 범위 모두 0.0. 이 작은 이동 시험은 통과했으나 물리적 즉시 정지 시간/여러 관절/모델 동작 중 정지/전체 LF-12 완료를 뜻하지 않는다.

현재 연결과 자세를 유지하고 다음 명령으로 읽기 전용 후보를 저장한다. 재보정·새 후보 설치·이동·재개는 필요 없다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py capture-home --trial "$trialFile"
```

HOME_CANDIDATE_SAVED, movement_commands_sent=0이면 기존 소유자의 현재 자세 후보와 Windows 파일 경로가 출력된다. home_approved=false, path_verified=false는 아직 목표 자세/복귀 경로를 확정하지 않았다는 정상 표시다. 프로그램은 약 1초간 정지 상태와 관측 자세의 안정성을 확인하고 기록 중 소유자/세대/모드 변화가 있으면 저장을 중단한다. 초기 동작 검증 기준인 관측 변화 0.5 정규화 단위 이하는 기계 안전 범위나 충돌 회피 기준이 아니다. 다음 작업은 후보 자세를 사용자가 원하는 대기 자세와 대조하고, 실제 배치에서 복귀 경로와 Home 중 정지 시험을 별도로 준비하는 것이다.
