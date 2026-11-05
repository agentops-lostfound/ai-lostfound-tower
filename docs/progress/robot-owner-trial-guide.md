> **11월 5일 정정:** `--sync-goal`은 사용 중단되어 실행 전 거부된다. 목표값 기록 후 6개 관절의 토크 ON이 실제 관측됐다. 아래 과거 목표값 동기화 절차는 재실행하지 않는다.

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

## 기존 화면에 근거리 Home 버튼 추가 후 연속 시험

사용자 지시대로 접힌 Home 설정과 기존 정지 관문을 이어서 사용한다. 현재 Home에서 맨 아래 좌우 회전 차이 1.0 정규화 단위 이내, 나머지 관절 차이 각 0.2단위 이내일 때만 실험용 복귀를 허용한다. 다른 관절과 집게는 출발 시 측정 위치를 유지한다. 임의 작업 자세에서 접힌 자세로 가는 일반 경로는 여전히 미검증이며 설정의 motion_enabled/path_verified를 승인 상태로 바꾸지 않는다.

기존 소유자 패치를 재설치하지 않는다. 정지 상태에서 패널 서버만 Ctrl+C 후 다음과 같이 갱신한다. Studio 연결·보정·Home 목표는 유지한다.

```powershell
git pull --ff-only origin pil2ya
$trialFile = Get-ChildItem ".\outputs\robot-owner-trial\*\trial.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName
py -3.11 .\tools\prepare_robot_owner_trial.py panel --trial "$trialFile"
```

브라우저 http://127.0.0.1:8770 을 새로고침하면 빨간 정지 버튼과 ‘접힌 대기 자세 복귀 · 근거리 시험’ 버튼이 보인다. Home은 빈 집게·고정 베이스·빈 공간을 확인하는 별도 확인창을 거쳐야 한다. 작업은 별도 통신 프로세스에서 실행하고, 정지 전송은 독립된 기존 작업자를 사용한다. 중복 Home은 409로 거부한다. 시작 전 상태 불일치/범위 이탈로 거부된 Home은 다른 진행 작업을 임의 정지시키지 않는다. 통신/실행 오류로 종료 상태가 불명확하면 같은 소유자 세션에 정지를 시도하고 Home 재시작을 막는다.

다음 세 가지를 중간 채팅 확인 없이 순서대로 진행할 수 있다. 오류나 예상 밖 움직임이 있으면 후속 시험을 중단한다.

1. 현재 자세에서 Home 클릭: 이미 목표 범위이면 ‘이미 Home 범위 안에 있습니다 · 이동 없음’이 정상이다.
2. 다른 터미널에서 기존 move-test를 한 번 실행하고 이번에는 제한된 이동을 끝까지 둔다. 자동 종료 정지 후 Home 클릭: ‘Home 도달 · 유지 명령 완료’가 정상이다.
3. move-test를 다시 한 번 끝까지 둔 후 Home 클릭. 상단 상태가 ‘이동 허용 상태’가 되면 빨간 정지 클릭: ‘Home 중단 · 자동 재시작 없음’과 실제 팔 자세 유지를 확인한다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py move-test --trial "$trialFile" --confirm-ready
```

2·3번의 move-test는 Home에서 조금 떨어지기 위한 것이므로 여기서는 MANUAL_STOP_NOT_OBSERVED + hold_commanded_after_trial=true가 정상이다. Home 도중 정지한 뒤 자동 복귀를 재개하지 않는다. 현재 범위를 벗어나면 강제 Home하지 않고 새 경로 확인을 요구한다. 시험 후 화면의 Home 상세 JSON에서 HOME_REACHED 또는 HOME_STOPPED와 유지 확인을 읽는다. 목표 도달 허용 오차는 정규화 0.2단위이며 기계 안전 범위나 정지 최악 지연 보장이 아니다.

코드 검증: 전체 180개 시험 실행, 2개 건너뜀. 근거리 복귀·중간 정지·이미 도달·범위 밖 거부·확인/세대 오류·카운트다운 취소·통신 실패 시험 통과. HTTP Home 확인/중복 차단·Home 진행 중 별도 정지 응답·시작 전 거부 시 다른 작업 미정지 시험 통과. 실제 Zenoh 1.10.2 + 가짜 소유자 + 화면용 stdin 작업자를 사용해 HOME_REACHED 및 8개 목표 후 HOME_STOPPED를 확인했다. 사용자 실물 Home 결과는 아직 없다.


## 전원 재인가 후 보정 불일치 조사 · 11월 5일

사용자가 로봇 전원과 PC를 재시작한 뒤 읽기 전용 preflight에서 보정 불일치가 다시 확인됐다. 변경된 관절과 원인은 아직 미확인이다. 기존 시험 기록을 유지하며 아래 진단으로 실제 보드값·기준값·차이·현재 토크를 보존한다. 모터 레지스터 쓰기는 수행하지 않는다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py diagnose --trial "$trialFile"
```

`CALIBRATION_MISMATCH`는 차이를 수집했다는 뜻이며 복구 완료가 아니다. JSON과 Windows 백업이 생성되면 차이를 검토한 뒤 다음 조치를 결정한다. `CALIBRATION_MATCH`여도 토크와 목표값을 별도로 검토해야 한다. 조사 중에는 Studio 연결, Home 이동, 목표값 동기화, 기존 보정 스크립트 재실행을 진행하지 않는다. 전원 재인가와 PC 재시작 중 어느 과정에서 바뀌었는지는 아직 구분되지 않았다.


## 목표값 기록 후 토크 ON · 11월 5일

- 팔로워 모델 번호 777, 펌웨어 major=3/minor=10, 6개 관절 모두 동일하다.
- EEPROM 잠금 해제→최종 보정값 기록→재잠금 후 사용자가 전원 재연결 시험을 진행했고, 이후 보드값 6개 모두 일치했다. PC 재시작 단독 시험은 아직 별도로 수행하지 않았다.
- 목표값 동기화 전 토크 0, 기록 후 6개 모두 토크 1이 확인됐다. 이후 명시적 토크 OFF 후 보정값 일치, 목표값=현재값, 전 관절 토크 0을 확인했다.
- 확인한 LeRobot write 및 scservo_sdk 1.0.0 전송 함수는 별도의 토크 ON 명령을 추가하지 않는다. 펌웨어 동작의 공식 확정은 아니다.
- 유사 보고: https://github.com/huggingface/lerobot/issues/3585 . 목표값 쓰기의 토크 자동 활성화와 범위 밖 목표 위험에 관한 사용자 보고로, 제조사 보증이나 이 장비의 원인 확정 자료는 아니다.
- 기존 `--sync-goal`을 토크 OFF 작업으로 취급한 가정을 폐기하고 호스트/컨테이너/함수 입구에서 차단했다. 시작 시 목표값 쓰기는 실제 구동 가능 단계로 설계해야 한다. 현재 Home 실물 시험 재개는 보류한다.


## Home 근거리 재시험 · 11월 5일

사용자 Home revision 2에서 HOME_ALREADY_REACHED 및 sent_targets=0 확인. 수동 정지 시험은 pan -3.8788326→-3.5833025, 관측 차이 0.29553(4틱), 나머지 관절 불변, 정지 후 관측 구간 변화 0으로 종료됐다. 이어진 Home 요청은 60회 접수됐으나 위치가 그대로여서 HOME_ABORTED(도달 오차 확인 실패), 종료 정지·유지 완료를 확인했다. 설치 드라이버의 오프라인 변환은 pan 2151→2147, 다른 관절 목표 불변으로 정상이다. CW/CCW 데드존 1만으로 실패 원인은 확정되지 않는다. PID·허용 오차는 변경하지 않는다.

`home-offset`은 현재 위치에 계속 더하는 대신 선택한 Home pan+0.8로 한정한다. 시작 및 관측 위치는 Home으로부터 1단위 안, 다른 관절은 Home 대비 0.2단위 안이어야 한다. 기존 회당 이동 상한 1단위도 유지한다. 이미 목표 근처면 이동하지 않는다. 기존 소유자와 정지 화면 및 --confirm-ready가 필요하고, 자동 연결/보정/토크 ON/설정 변경을 제공하지 않는다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py home-offset --trial "$trialFile" --confirm-ready
```

정상 동작이면 HOME_OFFSET_SEQUENCE_COMPLETE와 종료 정지·유지 완료를 확인한다. 이는 요청 시퀀스 완료이며 실제 위치 확인은 final_positions, offset_reached를 함께 본다. 이어 패널 Home을 한 번 실행한다. Home 및 offset 결과의 position_trace는 표본 요청 목표와 관측 pan 위치이며, queued_only는 모터 Goal 레지스터 기록 성공을 보장하지 않는다. 미이동을 성공으로 처리하거나 허용 오차를 완화하지 않는다. Home의 정지 허용 경로·기존 소유자 패치는 변경하지 않았다. 갱신된 Home 결과를 받으려면 패널을 재시작한다.


## 미이동 관측 후 실제 목표 읽기 추가 · 11월 5일

Home 기준 +0.8 준비 시험에서 시작 pan=-3.4355376, 목표=-3.0788326, 요청 60회 접수, 관측 변화 0, offset_reached=false, 종료 정지·유지 완료가 확인됐다. 시작이 이미 Home보다 약 0.4433 높아서 실제 추가 목표 차이는 약 5틱이다. 미세 거리 영향은 여전히 가능하지만 현재 자료로 원인을 확정할 수 없다. 미이동을 성공으로 취급하지 않고 거리·허용 오차·PID를 추가 변경하지 않는다.

진단 연결부는 기존 소유자 스레드에서 드라이버 send_action 반환 뒤 pan 모터의 Goal_Position(주소 42, 2바이트)을 읽는다. 기존 전송 이외에 모터 레지스터 쓰기는 추가하지 않는다. attempts/driver_calls_returned/readbacks, requested_pan_raw/observed_goal_raw, 오류를 status.delivery에 보존하고 Home/offset 결과에도 정지 전 사본을 남긴다. 요청 접수와 드라이버 호출 및 모터 목표 읽기를 구분한다. 목표값 일치는 실제 이동·토크·집기 성공을 의미하지 않는다. 읽기 오류/불일치는 기존 gate의 정지 래치를 세운다. 실제 정지 시간 보장은 아니며, 요청 처리당 읽기 I/O 1회가 추가된다.

```powershell
py -3.11 .\tools\prepare_robot_owner_trial.py telemetry-upgrade --trial "$trialFile"
```

Studio Connect OFF, runtime 종료, 패널 종료 후 활성 USB 소유자가 없어야 한다. 활성 프로세스·알 수 없는 설치 변경이면 거부한다. 기존 진입점·명령 gate는 그대로 두고 연결부만 교체한다. 원본 백업과 이전 후보는 보존하고 새 백업을 컨테이너 및 Windows에서 검증한 뒤 같은 trial.json을 갱신한다. Windows 사본/기록 저장 실패 시 이전 연결부 복원을 시도한다. 새 후보를 처음부터 만들거나 보정할 필요는 없다. 결과 TELEMETRY_UPGRADED_NO_HARDWARE_CONNECTION 또는 TELEMETRY_ALREADY_INSTALLED는 설치 확인이며 하드웨어 연결·토크 ON·시험을 수행하지 않는다. 적용 후 최신 패널을 재시작해야 한다. 원래 Home 실패는 그대로 미해결이며 복귀 중 정지 시험도 아직 미실시다.

### 실제 목표 읽기 확인 후 재시험


사용자 결과: attempts=60, driver_calls_returned=60, readbacks=60, 마지막 요청/모터 Goal_Position=2158 일치, 관측 위치는 pan 약 2153에서 변화 0. 요청 전달과 목표 기록은 확인됐으나 미이동 원인은 미확정이다. 마지막 목표 직후 정지를 요청하던 offset 시험을 보완해 최대 2초간 목표를 유지하며 관측한다. 정지 요청은 대기 중에도 처리한다.

`home-offset --home-side negative`는 Home-0.5를 목표로 사용한다. 현재 Home+0.443 부근에서는 약 13틱 거리이고, 회당 1단위 및 Home 기준 1단위 범위와 다른 관절 0.2 허용 조건은 그대로 유지한다. 한도를 넘는 시작 자세면 이동을 거부하며 반복 실행으로 거리를 누적하지 않는다. PID·Home 성공 허용 오차는 변경하지 않았다.

소유자 진단은 주소 40부터 18바이트를 한 패킷으로 읽어 토크·목표·현재 위치를 함께 기록한다. 읽기 요청 수는 기존 목표 읽기와 동일하게 1회이며 응답 길이는 증가한다. `delivery`의 원시 위치와 토크는 해당 목표 전송 직후의 표본이고, 2초 관측 구간 위치는 `position_trace`의 settle 표본을 함께 본다. 최신 연결부 적용은 기존 `telemetry-upgrade`로 수행하며 기존 trial과 원본 백업을 유지한다. 이 추가 시험은 아직 실물 미실행이다.

### 반대 방향 실물 이동 확인 · 11월 5일

사용자가 눈으로도 이동을 확인했다. Home-0.5 시험의 시작 pan=-3.4355376, 목표=-4.3788326, 최대 관측 이동량=0.5910599(약 8틱), 종료 위치=-3.9527152(시작 대비 약 7틱)였다. 60회 드라이버 호출 및 목표 읽기 성공, 마지막 요청/실제 Goal=2140 일치, 당시 Present=2145와 Torque_Enable=1을 확인했다. 2초 관측에서도 pan=-4.0265975로 유지되어 목표에는 미도달(offset_reached=false). 종료 정지·유지 명령 완료, 종료 후 pan 관측 폭은 0.0738823(1틱), 다른 관절 변화는 0이었다.

작은 목표 차이에서 응답이 나타나지 않고 더 큰 반대 방향 요청에서 응답한 사실은 확인됐지만 마찰·유격·제어 잔류 오차의 기여는 분리되지 않았다. 앞선 실패를 전송 불능으로 단정하지 않는다. 종료 위치는 저장 Home pan=-3.8788326과 약 0.0739 차이여서 현재 Home을 실행하면 이동 없는 판정이 예상된다. 정확한 offset 도달·실제 Home 복귀 성공·복귀 중 정지 시험은 별도 미완료이며 PID·허용 오차는 변경하지 않았다.

### 양방향 응답 비교 · 11월 5일

양수 방향 재시험은 시작 pan=-3.9527152, 목표=-3.0788326, 최대 관측 이동량=0.5910602(약 8틱), 종료 pan=-3.4355376(시작 대비 약 7틱)였다. 누적 드라이버 호출·목표 읽기 60→120, 마지막 요청/실제 Goal=2158 일치, 해당 전송 직후 Present=2154 및 토크 1을 확인했다. 2초 관측 위치는 pan=-3.3616550에서 유지되어 목표와 약 4틱 차이가 남았다. 종료 정지·유지 완료, 종료 후 전 관절 관측 폭은 0. 다른 관절 위치는 유지됐다. offset_reached=false로 정확한 목표 도달은 통과하지 않았다.

음수 방향 5틱, 양수 방향 4틱의 잔류 오차가 관측됐다. 현재 Home 허용 오차 0.2 정규화 단위는 pan에서 약 2.7틱이므로 실측 잔류 오차보다 좁다. 마찰·유격·제어 특성의 기여는 아직 분리하지 못했으며 데드존 설정만으로 설명하지 않는다. 사용자의 Home 요구 정확도를 확인하기 위해 (1) 접힌 대기 자세의 pan 허용 오차를 약 6틱으로 조정하면서 실제 복귀 움직임도 검증하거나 (2) 현 기준을 유지하고 제어 응답부터 개선하는 선택을 제시했다. 선택 전에는 PID·성공 기준을 변경하지 않았고 추가 이동·Home 시험도 수행하지 않았다.
