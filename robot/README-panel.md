# SO-101 티칭 패널

## 최신: 버튼 GUI + 외부 so101-control (11/5)

`robot.teaching_gui --live`의 기본 백엔드를 외부 `so101-control.move_to_joints()` + LeRobot으로 교체했다. 기존 Studio 패치/Panel.next_step 경로는 기본 LIVE GUI에서 사용하지 않는다. 아래 OpenCV·Studio 관련 절은 이전 구현의 기록이다.

```powershell
cd C:\Users\user\AI-LostFound\team-repo
& ..\.venv-robot-panel\Scripts\python.exe -m robot.teaching_gui --live
# 또는
powershell -NoProfile -ExecutionPolicy Bypass -File robot/launch_live_panel.ps1
```

외부 워커는 기존 Docker Python과 `outputs/external/so101-control/src/so101_control`, `outputs/so101_vendor_trial/calibration.json`을 사용한다. 배포 시 임시 폴더 `/tmp/lf-teaching`에 코드/보정 사본을 복사한다. Windows 환경에 LeRobot을 설치하지 않는다. 해당 로컬 외부 소스/보정 사본은 Git에 포함되지 않으므로 다른 PC에서는 별도 준비가 필요하다. Studio 또는 다른 제어기가 포트를 점유하면 연결을 거부한다. 자동으로 기존 제어기를 종료하지 않는다. 모터 보정/PID를 다시 쓰거나 토크를 전환하지 않고 기존 설정을 확인한다. 토크가 꺼져 있으면 연결 오류를 표시한다.

UI 표시·poses.json·CSV는 기존 Studio normalized 단위를 유지한다. 기존 보정으로 정수 encoder tick을 거쳐 LeRobot degrees로 변환한다. 저장된 사용자 자세를 덮어쓰거나 다른 단위로 다시 저장하지 않는다. 그리퍼는 이동 시작 실측값을 유지한다.

시작은 STOPPED. Repair HOLD → 자세 선택/Load preview → Review target → Approve ONE stage. 조그/숫자 입력은 목표 편집이며 별도 승인이 필요하다. 시간 선택 1=5초, 2=4초, 3=3초. 전체 시간의 앞 80%에 목표를 보간하고 마지막 20%는 최종 목표를 유지하여 실제 모터 추종 시간을 확보한다. 목표 선행 제한은 10도다. 명령 발행에는 5초 마감과 실제 경과시간 기반 pacing을 적용한다. 최종 잔여 오차는 degrees로 표시하며, 제한 시간 종료/명령 완료를 정확한 도착으로 판정하지 않는다. OS·시리얼 블로킹 때문에 물리적 정지를 실시간 하드웨어 수준으로 보장하는 기능은 아니다.

GUI와 워커는 전용 stdin/stdout로 연결하고 외부 서버 포트를 열지 않는다. 이동은 워커 스레드에서 실행하여 STOP 입력을 별도 수신한다. 1.5초 이상 GUI heartbeat가 끊기면 중단하고 재승인을 요구한다. STOP/연결 종료 시 실측 자세를 한 번 hold 목표로 보낸다. Repair는 이전 동작을 자동 재개하지 않는다.

기존 OpenCV CLI는 별도 이전 구현으로 남아 있다. 이전 Studio GUI 경로를 명시적으로 선택할 때만 `--driver studio`를 사용한다. 기본 버튼 GUI의 명령을 이 옵션으로 바꾸지 않는다.

상태 로그: `outputs/robot_panel_live/connection_status.json`의 driver가 `so101-control`이어야 한다. 워커 오류 로그는 `vendor_worker.stderr.log`, 관절 명령/실측 기록은 컨테이너 `/tmp/lf-teaching/motion.jsonl`이다. 시작/재연결/자세 선택만으로 이동하지 않는다.

> 최신 상태(11/5): 실제 실행 이미지 기준 v4 패치를 백업 후 적용했고 Studio 재시작·hold 연결·실측6관절 수신을 확인했다. 저장한 home/raised/entry/observe를 outputs/robot_panel_live/poses.json에 넣었다. 관절 목표 이동 명령은 아직 보내지 않았다. 아래의 미설치 표기는 초기 준비 기록이며 이 문단과 실물 실행 절을 우선한다.

## 현재 실물 실행

```powershell
cd C:\Users\user\AI-LostFound\team-repo
powershell -NoProfile -ExecutionPolicy Bypass -File robot/launch_live_panel.ps1
# 또는
& ..\.venv-robot-panel\Scripts\python.exe -m robot.control_panel --live --connect-studio
```

--connect-studio는 실행 세션이 없을 때 등록 환경을 명시적으로 hold 모드로 시작한다. 관절 목표나 teleop 명령은 보내지 않지만 장치 연결 및 기존 보정에 따른 드라이버 초기화가 수행된다. 팔과 전원을 준비한 뒤 사용한다. 플래그가 없으면 기존 hold 세션에만 붙는다. 중복 패널을 실행하지 않는다.

시작은 STOPPED다. R로 상태 복구 후 L→entry→Enter로 저장한 진입 자세를 미리볼 수 있다. 여기까지는 이동하지 않는다. 값과 경로를 확인한 뒤 Enter를 두 번 누르면 해당 한 단계의 이동을 승인한다. Home/펼침 등 다른 자세로 곧바로 이동할 때도 경로는 미검증이다.

커스텀 자세 파일은 outputs/robot_panel_live/poses.json, CSV는 같은 폴더 observations.csv다. --import-recorded는 없는 이름만 추가하고 사용자가 수정한 기존 자세를 덮어쓰지 않는다.

전용 환경 설치 확인: Python3.11.18, numpy2.4.6, opencv-python5.0.0.93, websocket-client1.9.2. 기존 비전/Qwen 환경은 변경하지 않았다.

실행 컨테이너의 /app/application/backend/src 아래3개 파일에 적용했으며 WSL checkout은 덮어쓰지 않았다. WSL checkout과 실행 이미지 API가 달라 실행 이미지 원본으로 패치를 생성했다. 백업 outputs/studio_panel_original_v4, 적용본 outputs/studio_panel_patch_v4. 현재 컨테이너 재시작에는 유지되지만 컨테이너 재생성/이미지교체 시 사라질 수 있다. 재적용은 원본 해시와 버전을 확인해야 한다. 이전 v2/v3를 실행 이미지에 덮어쓰지 않는다.

기본 실행은 모의 모드다. 관절값 단위는 도/라디안이 아닌 Studio normalized다. 몸통 -100..100, 그리퍼0..100. 이 버전은 그리퍼 이동을 잠그고 팔5관절만 조절한다.

기본 창은1040×650이다. 크기를 바꾸려면 `--scale 0.625`(800×500) 또는 `--scale 1`(1280×800)을 붙인다. 창 테두리를 드래그해서 조절할 수도 있다.

## 바로 실행: 로봇을 움직이지 않는 모의 모드

team-repo에서:

```powershell
& ..\.venv-vision\Scripts\python.exe -m robot.control_panel
```

지금 기록한4개 자세를 명시적으로 가져오려면:

```powershell
& ..\.venv-vision\Scripts\python.exe -m robot.control_panel --import-recorded outputs/robot_poses
```

기록된 끝 자세만 가져온다. 두 자세 사이가 턱을 피하는 경로라는 의미는 아니다. 모의 모드와 실물 모드의 저장 폴더를 기본적으로 분리한다.

## 키

| 키 | 기능 |
|---|---|
| Space | 소프트웨어 정지 래치. 대기 목표 취소·재승인 필요 |
| R | 리페어: 연결·관측 상태 확인 후 목표를 현재값으로 재설정. 홈복귀/재보정/이전 이동 재개 없음 |
| 1..6 | 모터 선택 (6번 그리퍼 편집 잠금) |
| +/- | 선택 목표1 normalized 증감. 실제 이동은 하지 않음 |
| T | 선택 모터의 정확한 목표 숫자 입력 후 Enter |
| Enter 두 번 | 목표 검토 → 해당 한 단계 이동 승인 |
| Z / X / C | 속도1/2/3: 명령당0.05/0.10/0.25 normalized, 최대8Hz |
| S | 현재 측정 자세를 이름으로 저장. 이름 입력 후 Enter |
| L | 저장 자세 이름 입력·미리보기. 이동은 별도 Enter 두 번 |
| H | home 미리보기 |
| N | 다음 번호 자세 미리보기: home→raised→entry→observe |
| B | 위 순서를 뒤집음. N으로 하나씩 선택하고 각각 승인 |
| V | 현재 측정 관절값 CSV 한 줄 저장 |
| A | 1Hz CSV 자동 기록 켜기/끄기 |
| Esc / 창 닫기 | 패널 종료·소프트웨어 정지 요청 |

문자 입력 중 Space도 정지를 우선한다. 이름은 영문/숫자/_/-만 허용. 한글 UI 대신 OpenCV 기본 글꼴이 표시 가능한 영어 레이블을 쓴다.

poses.json과 observations.csv는 outputs/robot_panel_sim 또는 outputs/robot_panel_live에 저장된다. CSV에 시각(UTC)·단위·속도 단계·6관절 측정값을 기록한다. 미리보기 목표값을 실측으로 저장하지 않는다.

## 실물 연결 준비 상태

**실물 Studio 패치는 아직 설치하지 않았다. 실물 통합 시험과 자동 이동은 미실시다.** `--live`는 기존 실행 중인 hold 세션만 attach하는 패널 전용 /runtime/manual/ws가 필요하다. 미설치 서버에는 연결되지 않으며 새 runtime/serial 연결·토크 활성화를 하지 않는다.

패치 생성:

```powershell
wsl -d Ubuntu-24.04 --exec python3 `
  /mnt/c/Users/user/AI-LostFound/team-repo/robot/stage_studio_patch.py `
  --source /home/user/physical-ai-studio/application/backend/src `
  --output /mnt/c/Users/user/AI-LostFound/team-repo/outputs/studio_panel_patch_v3
```

v1/v2는 이전 관절목표만의 패치이므로 새 패널에 필요한 endpoint/stop/repair가 없다. 새 패치 검토·백업·적용·재시작은 팔이 안정된 상태에서 별도 진행한다. 설치됐다고 간주하고 실행하면 안 된다.

실물 패널용 의존성은 기존 환경을 변경하지 않도록 별도 환경에 설치할 수 있다:

```powershell
& ..\.venv-vision\Scripts\python.exe -m venv ..\.venv-robot-panel
& ..\.venv-robot-panel\Scripts\python.exe -m pip install -r robot/requirements-panel.txt
# 아래 실행은 새 패치 설치·검증 및 팔 준비 확인 후에만 사용
& ..\.venv-robot-panel\Scripts\python.exe -m robot.control_panel --live --import-recorded outputs/robot_poses
```

이 안내 작성 시 위 전용환경 생성/설치는 실행하지 않았다. 실제 설치 package 버전은 이후 별도 기록한다. 화면만 시험하려면 `--render-only outputs/robot_panel_sim/preview.png`를 사용한다.

## 정지와 제한의 의미

- Space는 물리 비상정지가 아니다. 서버가 현재 관측 관절값을 hold 목표로 삼고 추가 수동 명령을 막는다. 통신 장애 시 서버에 정지 요청이 도달했다고 보장할 수 없다. 하드웨어 전원/비상정지 수단은 따로 확보한다.
- 패널 분리 시 서버도 stop을 요청한다. Studio 세션은 종료하거나 토크 해제하지 않는다. 정지/복구 후 목표를 다시 선택·승인해야 한다.
- 속도3단계는 정규화 명령 변화율이다. 관절별 실제 도/초·TCP속도·충돌 여유 보장이 아니다. 드라이버 goal_time을 속도 제한으로 사용하지 않는다.
- 실시간 관측 stale, 서버 error, 목표 추종 응답 timeout이면 진행을 막는다. 모드가hold가 아니면 명령을 보내지 않는다. 다른 Studio 창에서 텔레옵/정책을 동시에 켜지 않는다.
- 새 endpoint는 새로 장치를 열지 않는다. 기존 runtime generation에 붙고 한 팔에 수동 패널1개만 허용한다. 기존 GUI나 다른 자동화의 제어권까지 완전히 잠그는 기능은 아니다.
- 그리퍼 위치 제어·기구 수리·펌웨어·보정 변경·전체 경로 자동재생은 포함하지 않는다. 요청한 리페어는 상태 복구로 구현했다.

선택적 영상: `--camera-url http://127.0.0.1:8765/camera.mjpg` (기존 손목 브리지). 카메라 설정은 변경하지 않는다. 미리보기는 제어와 비동기이며 시각적 충돌 감지가 아니다.
