# robot

본센터 로봇팔 SO-101 (LF-11·12): 보관함 보관·수령대 전달, 반환 안전 규칙(승인 기록 없으면 정지)

Home 목표는 [config/home_pose.json](config/home_pose.json)의 사용자 지정 접힌 자세다.
로컬 설정과 변경 이력은 `outputs/robot-home/`에 저장하며 [home_profiles.py](home_profiles.py)로 읽는다.
`tools/configure_robot_home.py set --candidate <기록한 후보 JSON>`으로 교체할 수 있다.
일반 작업 자세에서의 복귀 경로는 아직 활성화하지 않았다.
`tools/robot_home_return.py`와 정지 화면은 Home 근처의 맨 아래 회전만 제한 복귀하는 별도 시험을 지원한다.
정지 버튼은 Home 중에도 동작하며, Home 중단 후 자동 재개하지 않는다.
