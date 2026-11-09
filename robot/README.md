# robot

**현재 운영 방식: 미리 티칭한 커스텀 자세 8개를 선택해 이동한다.** `home`과 함께 `pose_1`~`pose_8`을 저장했다. GUI의 **커스텀 1~8** 버튼은 자세를 미리 불러오며 이동은 단계별 승인 절차를 거친다. [실행 및 사용 절차](README-panel.md).

오늘의 모델 변경·티칭·GUI 시험·실물 연결 결과와 남은 작업: [2026-11-05 작업 정리](../docs/reports/2026-11-05-daily-update.md).

버튼형 티칭 GUI: [검증 결과와 실행법](../docs/reports/2026-11-05-teaching-gui-verification.md). 기본은 Simulation이다. Studio v4 패치는 이전에 설치됐지만 저장 자세의 실물 이동은 검증 중이다.

기존 키보드 제어 패널: [실행 방법과 키 설명](README-panel.md).

본센터 로봇팔 SO-101 (LF-11·12): 보관함 보관·수령대 전달, 반환 안전 규칙(승인 기록 없으면 정지)

Home 목표는 [config/home_pose.json](config/home_pose.json)의 사용자 지정 접힌 자세다.
로컬 설정과 변경 이력은 `outputs/robot-home/`에 저장하며 [home_profiles.py](home_profiles.py)로 읽는다.
`tools/configure_robot_home.py set --candidate <기록한 후보 JSON>`으로 교체할 수 있다.
일반 작업 자세에서의 복귀 경로는 아직 활성화하지 않았다.
`tools/robot_home_return.py`와 정지 화면은 Home 근처의 맨 아래 회전만 제한 복귀하는 별도 시험을 지원한다.
정지 버튼은 Home 중에도 동작하며, Home 중단 후 자동 재개하지 않는다.
