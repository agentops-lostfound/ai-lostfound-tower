# LF-11·12 정지·Home 작업 순서

2026-11-04. 사용자 요청: 모든 Git 브랜치에서 현 구현을 확인하고 지금 가능한 작업부터 순차 진행. 실물 구동은 별도 준비 확인 전 실행하지 않는다.

## 1/5 원격 브랜치 확인 — 완료

ls-remote로 확인한 현존 브랜치5개: main413d05b, LF-3-yolo-aruco fc38e55, jaemin04125f4, lf2/connect-intake-kiosk-api84bf82d, pil2ya993450d(조사 시작 시점). 로컬에 남은 origin/LF-2-haeundae-found-item-form은 현존 원격 목록에 없어 현재 작업 브랜치로 계산하지 않았다. 원격 삭제·로컬 브랜치 전환·병합은 수행하지 않았다.

모든 현존 브랜치의 파일 목록과 로봇 함수/Studio/runtime/명령 전송 참조를 검색했다. 각 robot 폴더에는 README만 있다. main·lf2에는 stop/home 관제탑 API·서비스·계약·모의 구현 및 시험이 있고, LF-3·jaemin·pil2ya는 일부 이전 관제탑 계약이다. 실제 SO101 제어 드라이버·Physical AI Studio runtime 연결·모터 정지/Home 구현은 찾지 못했다. 사용자 PC에 별도로 존재할 수 있으므로 부재를 일반화하지 않는다. 최신 main을 임의 병합하지 않고 새 계약을 기준으로 별도 설계한다.

## 2/5 로컬 Studio 읽기 조사 — 현재 단계

사용자 제공 스크립트 본문 확인: test_new_pair_teleop.py는 websocket 초기 follower/leader 연결→hold 확인→teleop15초→finally hold 확인→disconnect→별도 POST /api/runtime/sessions/rt-<follower>/stop 순서다. 연결/teleop 자체가 실제 구동이므로 진단용으로 재실행하지 않는다. hold가 실제 제어 루프/드라이버에서 무엇을 하는지는 backend source 검토 전 미확정이다.

home_new_follower.py는 Home 복귀 함수가 아니다. 토크OFF 확인 후 Operating_Mode를 쓰고 set_half_turn_homings()로 보정 offset을 저장하는 초기 중앙 자세 보정 스크립트다. 현재 최종 보정값을 덮어쓸 수 있으므로 robot_home 구현에 재사용/실행하지 않는다. /tmp sentinel 파일은 컨테이너 재생성 후 없을 수 있어 재실행 방지의 영구 보장이 아니다. 실제 정상 Home 동작은 저장된 안전 관절 자세/경로를 별도로 정의해야 한다. 다음은 컨테이너 backend runtime/robot 파일 위치와 설치된 LeRobot follower driver source 위치를 읽기 조회한다. 원본 로컬 스크립트/보정 JSON은 Git에 복사하지 않았다.

사용자 조회 확인(2026-11-04): physical-ai-studio-cuda가 Up3hours/healthy, WorkingDir=/app/application/backend, LeRobot0.6.0. Windows soarm-setup에 test_new_pair_teleop.py·home_new_follower.py·home_new_leader.py·보정/유지 점검 JSON·도구가 존재한다. 파일명만으로 Home 이동 구현이나 전원 재인가 검증 성공을 판단하지 않는다. 다음은 test_new_pair_teleop.py와 home_new_follower.py의 텍스트만 읽어 API·hold/disconnect·목표각 쓰기·캘리브레이션 여부를 확인하는 것이다. 이 단계에서 파일 실행·로봇 연결·모터 명령을 수행하지 않는다.

확인 대상은 기존 soarm-setup 도구 파일명, Docker 컨테이너 실행 상태·작업 경로·LeRobot 버전, 이후 관련 runtime·드라이버 소스다. .env·비밀값·DB·USB 연결·토크·세션·목표각은 변경하지 않는다. 임의 docker start/restart·USB attach·보정 스크립트 실행도 하지 않는다. 이 클라우드 localhost는 사용자 PC와 다르므로 사용자가 VS Code PowerShell에서 읽기 명령을 실행한다.

후속 코드 조사에서 hold/stop/disconnect의 실제 의미, ongoing 작업 취소·명령 발행 중단, torque 유지 여부, Home 경로·동시 호출·timeout을 확인한다. 기존 15초 teleop 스크립트는 실제 장비를 움직이므로 파일명만 보고 실행하지 않는다. 캘리브레이션·시연·학습 완료를 전제로 하지 않는다.

## 3/5 무동작 제어기와 모의 시험 — 다음

실제 API를 확인한 뒤 명령만 기록하는 부품으로 stop/home 의미를 구현한다. 같은 controller/취소 신호 공유, 별도 스레드 stop, 이후 이동 차단, 자동 Home 없음, Home 도중 stop, 오류 반환을 검증한다. 최신 main의 6함수 계약과 check_part에 맞추되 agents 공통 계약은 임의 변경하지 않는다. 아직 없는 approach/grasp 부품을 진짜로 구현한 척하지 않는다. 다른 담당 부품은 명시적 모의/연결 미완료로 둔다.

## 4/5 제한된 실물 정지·Home 시험 — 준비 확인 후

사용자가 보는 Studio 화면·장비 시리얼·현재 보정/자세·작업공간·실제 제어 구현을 확인한다. 학습 정책 없이도 일반 이동에서 정지·재시작 차단·저장된 안전 Home 경로를 시험할 수 있다. 정지는 무조건 토크 OFF가 아니며 팔/물품 낙하 위험을 고려한다. 초기 Home을 알려지지 않은 자세에서 즉시 명령하지 않는다. 자동 구동·재보정·학습을 이번 조사 명령에 섞지 않는다.

## 5/5 반환 경로·팀 연결 시험 — 후속

정상 물품 놓기·집게 분리·안전 이탈·대기 자세를 실제 배치에서 결정한다. 비상정지 후 Home은 직원 확인 버튼으로만 수행한다. GPU 사용권·mm 좌표/2마커 관문·인계 대기/직원 최종 인계와 연결한다. 학습된 SmolVLA가 준비되면 해당 정책 동작 중에도 같은 정지 경로가 작동하는지 추가 검증한다.

지금 가능한 작업은 2단계 조사와3단계 무동작 개발이다. 실제 집기 정책 학습·좌표 접근 구현 완료를 기다려야 시작할 수 있는 업무가 아니다. Jira LF-22~34의 개별 배정은 별도 조회가 없어 이 문서에서 추정하지 않는다.

## 2026-11-04 로컬 보정 불일치 복원 및 명령 관문 추가

사용자 보드 조회에서 리더 6관절은 최종 JSON과 일치했으나 팔로워 6관절은 모두 불일치했다. Studio GET의 팔로워 payload는 Windows 최종 JSON과 일치했다. 원인은 미확정이며 드라이버 재연결이 보정 EEPROM을 자동 복원한다고 가정하지 않는다.

Studio 세션 종료 후 /proc fd 조회로 두 USB 포트 소유자가 없음을 확인했다. 사용자가 팔로워를 받치고 토크 OFF를 승인했다. 최초 쓰기는 인자 순서 오류(KeyError: 0)로 실패했으며, write(data_name, motor, value)로 수정 후 6관절 토크 OFF를 확인했다. 실제 보드값을 영구 볼륨과 Windows에 백업하고, 최종 JSON으로 팔로워 보정을 기록한 뒤 readback 일치와 토크 OFF를 확인했다. 사용자는 이후 두 팔 비교값 모두 일치를 보고하고 calibration-restored-20261104-150021.json을 Windows에 저장했다. 현재 자세의 안전성·전원 재인가 후 유지·불일치 재발 원인은 별도 검증이 필요하다. 토크 자동 ON, Home, teleop는 수행하지 않았다.

robot/command_gate.py는 send/hold 콜백을 받는 연결 전용 기반 코드다. 초기 정지, 소유자 유지 성공 및 직원 확인 후 재개, 세대 번호로 늦은 추론 결과 폐기, 최신 목표만 유지, 전송 실패 시 재개 차단을 구현했다. I/O 동안 상태 잠금을 잡지 않아 정지 요청은 실행 중 I/O 완료를 기다리지 않는다. 이미 전송 허용된 I/O를 취소하거나 하드웨어 즉시 정지를 보장하지 않는다. tests/test_robot_command_gate.py는 통신 실패·실행 중 I/O·대기 목표 폐기를 가짜 콜백으로 검증한다.

이 관문은 아직 Studio owner의 Zenoh 전송부에 설치되지 않았다. 현 Studio 메시지는 목표와 goal_time만 보내므로 안전한 통합에는 소유자 측 stop/resume 처리 및 모든 목표의 세대 식별, 소유권 통제가 필요하다. 기존 send_action을 새 관문에 단순 연결하는 것만으로 우회 경로가 제거되지는 않는다. 실제 장비 연결 전에 해당 프로토콜 통합 및 모의 시험을 완료해야 한다. 안전 Home 자세·경로도 아직 미정이다.
