# 기존 SO-101 제어 도구 검토·공식 dry-run

자체 패널 이동의 추종 timeout이 발생해 사용자가 기존 제어 프로그램 검토를 요청했다. 자체 패널의 실제 저장자세 이동 성공은 검증되지 않았다. 이전 연결 성공 표기는 관절 읽기 성공과 구분한다.

## 검토 대상

- 원본: https://github.com/vi-vi-3482/so101-control
- 검토 커밋:7461e9ed741bdc607818b3f819a8ce8e75f869f5.
- 로컬 검토 사본: outputs/external/so101-control (Git 공유 제외)
- pyproject:0.1.1, 개발단계Alpha, Python>=3.12, GPL-3.0-only.
- README는 Windows 직접 설치를 지원하지 않고 WSL 사용을 안내한다. 의존성 lerobot[kinematics,feetech]>=0.5.1, cmeel-urdfdom4.0.1, cmeel-tinyxml2 10.0.0.
- move_to_joints, home/rest, XYZ IK go_to_ee, CLI/dry-run이 있다. 완성 GUI·CSV/커스텀 프리셋 관리 패널은 아니다.

## 수행한 시험

기존 Studio에서 의존성 버전만 조회했다: Python3.13.16, LeRobot0.6.0, numpy2.2.6. placo는 미설치다. 기존 환경에 패키지를 설치하거나 보정을 수정하지 않았다.

현재 설치 이미지와 동일한 이미지를 사용해 별도 일회용 컨테이너를 생성했다. 네트워크 없음, USB/GPU 전달 없음, 읽기 전용 루트와 원본 소스 mount, capability 제거 조건이다. 원본 소스의 `python -m so101_control.cli --mode joint ... --dry-run`을 그대로 실행했다.

시험 목표(물품/실제 팔 목표가 아닌 임의 예): shoulder_pan5도, 나머지 팔0도, gripper50. duration1초/fps5의 계획을 출력하고 exit0으로 종료했다. 시작점은 실제 관절값이 아니라 라이브러리 기본 HOME_JOINTS다. 소스는 실제 LeRobot0.6.0으로 import됐고 mock IK 패키지는 사용하지 않았다. joint dry-run은 placo 없이 가능했지만 XYZ IK는 미시험이다.

## 채택 전 확인 사항

1. 이 도구의 팔 관절값은 degrees, XYZ는meters다. 기존 Studio normalized(-100..100)를 그대로 입력하지 않는다. 같은 보정정보로 단위를 대조해야 한다.
2. 기본 home은 중립 자세이고 기존 사용자의 접힌 home과 다르다. 기본 home/rest 명령을 그대로 실물에 실행하지 않는다.
3. move_to_joints는 시간 기반 선형 보간 후 send_action을 호출하는 작은 래퍼다. 코드 검토상 그 함수 자체에 장애물 회피·도착확인·우리 패널의 단계별 승인 기능은 없다. 기존 라이브러리라는 이유로 안전/완성도를 보장하지 않는다.
4. 실물 CLI는 SO101FollowerConfig(use_degrees=True)와 robot.connect(calibrate=False)를 사용한다. 다른 컨트롤러 드라이버이며 기존 Studio와 동시에 같은 포트를 열지 않는다. 이번 작업에서는 연결하지 않았다.
5. 변경 없이 별도 실행하는 검토 사본으로 보관했다. 팀 코드에 복사·통합하지 않았다. 라이선스와 배포 방식은 통합 시 검토한다.

실물 이동·정지·현재 보정 호환 검증은 미완료다. 당장 GUI가 우선이면 별도 후보 Haller HMI의 관절슬라이더/home/pose presets 부분을 검토하는 편이 더 직접적이다: https://github.com/oscardvs/haller_ws . 이 후보는 이번 턴에 설치하지 않았다.
