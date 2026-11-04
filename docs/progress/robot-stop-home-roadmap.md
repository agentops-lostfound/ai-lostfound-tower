# LF-11·12 정지·Home 작업 순서

2026-11-04. 사용자 요청: 모든 Git 브랜치에서 현 구현을 확인하고 지금 가능한 작업부터 순차 진행. 실물 구동은 별도 준비 확인 전 실행하지 않는다.

## 최신 상태

팀원은 [현재 진행 요약](pil2ya-team-update-2026-11-04.md)을 먼저 확인한다. 아래 계획과 날짜별 기록은 진행 당시의 이력이며 현재 상태는 다음과 같다.

| 단계 | 현재 상태 |
| --- | --- |
| 1/5 원격 브랜치 조사 | 완료. 조사 당시 기준이며 이후 최신 main 통합은 별도 |
| 2/5 로컬 소스·보정 조사 | 조사·복원/readback 확인. 보정 불일치와 일시적 토크 검증 실패 원인은 미확정 |
| 3/5 무동작·통신 구현 | 정지·근거리 Home 코드 및 모의/가짜 장비 통신 시험 완료 |
| 4/5 제한 실물 시험 | 한 관절의 작은 이동 중 수동 정지 확인. Home 후보 저장·접힌 목표 선정 완료. 실물 Home 도달/중간 정지 결과 대기 |
| 5/5 반환·팀 연결 | 미완료. 일반 복귀 경로·모델/VLA·관제탑 backend·전체 반환 시험 필요 |

## 1/5 원격 브랜치 확인 — 완료

ls-remote로 확인한 현존 브랜치5개: main413d05b, LF-3-yolo-aruco fc38e55, jaemin04125f4, lf2/connect-intake-kiosk-api84bf82d, pil2ya993450d(조사 시작 시점). 로컬에 남은 origin/LF-2-haeundae-found-item-form은 현존 원격 목록에 없어 현재 작업 브랜치로 계산하지 않았다. 원격 삭제·로컬 브랜치 전환·병합은 수행하지 않았다.

모든 현존 브랜치의 파일 목록과 로봇 함수/Studio/runtime/명령 전송 참조를 검색했다. 각 robot 폴더에는 README만 있다. main·lf2에는 stop/home 관제탑 API·서비스·계약·모의 구현 및 시험이 있고, LF-3·jaemin·pil2ya는 일부 이전 관제탑 계약이다. 실제 SO101 제어 드라이버·Physical AI Studio runtime 연결·모터 정지/Home 구현은 찾지 못했다. 사용자 PC에 별도로 존재할 수 있으므로 부재를 일반화하지 않는다. 최신 main을 임의 병합하지 않고 새 계약을 기준으로 별도 설계한다.

## 2/5 로컬 Studio 읽기 조사 — 초기 계획 및 이력

사용자 제공 스크립트 본문 확인: test_new_pair_teleop.py는 websocket 초기 follower/leader 연결→hold 확인→teleop15초→finally hold 확인→disconnect→별도 POST /api/runtime/sessions/rt-<follower>/stop 순서다. 연결/teleop 자체가 실제 구동이므로 진단용으로 재실행하지 않는다. hold가 실제 제어 루프/드라이버에서 무엇을 하는지는 backend source 검토 전 미확정이다.

home_new_follower.py는 Home 복귀 함수가 아니다. 토크OFF 확인 후 Operating_Mode를 쓰고 set_half_turn_homings()로 보정 offset을 저장하는 초기 중앙 자세 보정 스크립트다. 현재 최종 보정값을 덮어쓸 수 있으므로 robot_home 구현에 재사용/실행하지 않는다. /tmp sentinel 파일은 컨테이너 재생성 후 없을 수 있어 재실행 방지의 영구 보장이 아니다. 실제 정상 Home 동작은 저장된 안전 관절 자세/경로를 별도로 정의해야 한다. 다음은 컨테이너 backend runtime/robot 파일 위치와 설치된 LeRobot follower driver source 위치를 읽기 조회한다. 원본 로컬 스크립트/보정 JSON은 Git에 복사하지 않았다.

사용자 조회 확인(2026-11-04): physical-ai-studio-cuda가 Up3hours/healthy, WorkingDir=/app/application/backend, LeRobot0.6.0. Windows soarm-setup에 test_new_pair_teleop.py·home_new_follower.py·home_new_leader.py·보정/유지 점검 JSON·도구가 존재한다. 파일명만으로 Home 이동 구현이나 전원 재인가 검증 성공을 판단하지 않는다. 다음은 test_new_pair_teleop.py와 home_new_follower.py의 텍스트만 읽어 API·hold/disconnect·목표각 쓰기·캘리브레이션 여부를 확인하는 것이다. 이 단계에서 파일 실행·로봇 연결·모터 명령을 수행하지 않는다.

확인 대상은 기존 soarm-setup 도구 파일명, Docker 컨테이너 실행 상태·작업 경로·LeRobot 버전, 이후 관련 runtime·드라이버 소스다. .env·비밀값·DB·USB 연결·토크·세션·목표각은 변경하지 않는다. 임의 docker start/restart·USB attach·보정 스크립트 실행도 하지 않는다. 이 클라우드 localhost는 사용자 PC와 다르므로 사용자가 VS Code PowerShell에서 읽기 명령을 실행한다.

후속 코드 조사에서 hold/stop/disconnect의 실제 의미, ongoing 작업 취소·명령 발행 중단, torque 유지 여부, Home 경로·동시 호출·timeout을 확인한다. 기존 15초 teleop 스크립트는 실제 장비를 움직이므로 파일명만 보고 실행하지 않는다. 캘리브레이션·시연·학습 완료를 전제로 하지 않는다.

## 3/5 무동작 제어기와 모의 시험 — 초기 계획

실제 API를 확인한 뒤 명령만 기록하는 부품으로 stop/home 의미를 구현한다. 같은 controller/취소 신호 공유, 별도 스레드 stop, 이후 이동 차단, 자동 Home 없음, Home 도중 stop, 오류 반환을 검증한다. 최신 main의 6함수 계약과 check_part에 맞추되 agents 공통 계약은 임의 변경하지 않는다. 아직 없는 approach/grasp 부품을 진짜로 구현한 척하지 않는다. 다른 담당 부품은 명시적 모의/연결 미완료로 둔다.

## 4/5 제한된 실물 정지·Home 시험 — 초기 계획

사용자가 보는 Studio 화면·장비 시리얼·현재 보정/자세·작업공간·실제 제어 구현을 확인한다. 학습 정책 없이도 일반 이동에서 정지·재시작 차단·저장된 안전 Home 경로를 시험할 수 있다. 정지는 무조건 토크 OFF가 아니며 팔/물품 낙하 위험을 고려한다. 초기 Home을 알려지지 않은 자세에서 즉시 명령하지 않는다. 자동 구동·재보정·학습을 이번 조사 명령에 섞지 않는다.

## 5/5 반환 경로·팀 연결 시험 — 후속

정상 물품 놓기·집게 분리·안전 이탈·대기 자세를 실제 배치에서 결정한다. 비상정지 후 Home은 직원 확인 버튼으로만 수행한다. GPU 사용권·mm 좌표/2마커 관문·인계 대기/직원 최종 인계와 연결한다. 학습된 SmolVLA가 준비되면 해당 정책 동작 중에도 같은 정지 경로가 작동하는지 추가 검증한다.

초기 조사 시점에는 2단계 조사와3단계 무동작 개발을 바로 시작할 수 있었다. 실제 집기 정책 학습·좌표 접근 구현 완료를 기다려야 시작할 수 있는 업무는 아니었다. Jira LF-22~34의 개별 배정은 별도 조회가 없어 이 문서에서 추정하지 않는다.

## 2026-11-04 로컬 보정 불일치 복원 및 명령 관문 추가

사용자 보드 조회에서 리더 6관절은 최종 JSON과 일치했으나 팔로워 6관절은 모두 불일치했다. Studio GET의 팔로워 payload는 Windows 최종 JSON과 일치했다. 원인은 미확정이며 드라이버 재연결이 보정 EEPROM을 자동 복원한다고 가정하지 않는다.

Studio 세션 종료 후 /proc fd 조회로 두 USB 포트 소유자가 없음을 확인했다. 사용자가 팔로워를 받치고 토크 OFF를 승인했다. 최초 쓰기는 인자 순서 오류(KeyError: 0)로 실패했으며, write(data_name, motor, value)로 수정 후 6관절 토크 OFF를 확인했다. 실제 보드값을 영구 볼륨과 Windows에 백업하고, 최종 JSON으로 팔로워 보정을 기록한 뒤 readback 일치와 토크 OFF를 확인했다. 사용자는 이후 두 팔 비교값 모두 일치를 보고하고 calibration-restored-20261104-150021.json을 Windows에 저장했다. 현재 자세의 안전성·전원 재인가 후 유지·불일치 재발 원인은 별도 검증이 필요하다. 토크 자동 ON, Home, teleop는 수행하지 않았다.

robot/command_gate.py는 send/hold 콜백을 받는 연결 전용 기반 코드다. 초기 정지, 소유자 유지 성공 및 직원 확인 후 재개, 세대 번호로 늦은 추론 결과 폐기, 최신 목표만 유지, 전송 실패 시 재개 차단을 구현했다. I/O 동안 상태 잠금을 잡지 않아 정지 요청은 실행 중 I/O 완료를 기다리지 않는다. 이미 전송 허용된 I/O를 취소하거나 하드웨어 즉시 정지를 보장하지 않는다. tests/test_robot_command_gate.py는 통신 실패·실행 중 I/O·대기 목표 폐기를 가짜 콜백으로 검증한다.

이 관문은 아직 Studio owner의 Zenoh 전송부에 설치되지 않았다. 현 Studio 메시지는 목표와 goal_time만 보내므로 안전한 통합에는 소유자 측 stop/resume 처리 및 모든 목표의 세대 식별, 소유권 통제가 필요하다. 기존 send_action을 새 관문에 단순 연결하는 것만으로 우회 경로가 제거되지는 않는다. 실제 장비 연결 전에 해당 프로토콜 통합 및 모의 시험을 완료해야 한다. 안전 Home 자세·경로도 아직 미정이다.

## 2026-11-04 소유자 JSON 연결부 및 설치 전 패치 후보

robot/owner_bridge.py는 소유자별 무작위 세션 ID, 정지 세대 번호, 재개 시 지정한 writer, 증가하는 sequence로 오래된/중복/다른 소유자 명령을 차단한다. 정지 접수 응답(stop_requested)과 소유 스레드의 위치 유지 목표 전송 완료(hold_commanded)를 구분하며 어느 것도 실제 속도 0 인증은 아니다. staff_confirmed는 호출자의 확인 표시로 인증 기능이 아니고, 실험용 연결은 로컬 전용이다. 현재 별도 웹 UI·인증·관제탑 API 연결은 없다.

검토한 원본 _owner_worker.py SHA256 fb01e47292a94c48fc00cb5e8ec42a4d6ec9d0987ecefaab0da6f60258a7b625에 대해서만 tools/prepare_robot_owner_patch.py가 별도 outputs 폴더에 후보를 생성한다. 원본 ZIP을 입력으로 사용하고 설치된 라이브러리/컨테이너를 변경하지 않는다. 초기 hold, 대기 목표 정지 폐기, 유효 신규 목표, 비대상 소유자 기존 경로의 4가지 모의 시험을 패치된 실제 _run_loop 함수에 대해 수행한다. SDK/Zenoh/USB는 실행하지 않는다.

후보 패치는 새 팔로워 ID 0f876b83-64cd-4bb9-9630-963eaeb3c0b7에서만 기존 /action 명령을 폐기하고 별도 /lf-safety queryable을 사용한다. 새 명령이 없으면 이동하지 않는다. leader·다른 ID의 소유자는 기존 경로를 유지한다. 대상에서는 allow_remote=True를 거부하고 검토한 SO101 클래스와 normalized follower만 허용한다. 실제 Zenoh 전송은 아직 시험하지 않았다. 따라서 기존 Studio Teleoperate·policy와 호환된다고 가정하지 않으며 현재 후보를 site-packages에 복사하지 않는다.

SO101 유지 콜백은 최신 raw 위치를 직접 읽어 raw 목표로 쓰며 토크를 켜지 않는다. 일반 normalized send_action을 유지에 사용하면 범위 밖 현재 자세가 clipping되어 움직일 수 있기 때문이다. 현재 드라이버 connect는 토크/설정 쓰기를 포함하므로 후보의 import·생성과 실제 연결은 구분한다. 준비 도구의 성공은 실제 장비 연결 승인이 아니다. 다음은 컨테이너 내부에서 설치하지 않는 Zenoh 모의 전송 시험, 원본 백업/복원 도구, 제한된 정지 시험용 조작 화면 준비다. 실제 Home 경로는 미구현이다.

## 2026-11-04 실제 Zenoh + 가짜 소유자 통신 시험

사용자가 패치 후보 a4add9deceb34f9ea9289c8843dc8aa9 생성과 소유자 루프 4개 시험 통과를 보고했다. tools/test_robot_owner_zenoh.py를 추가해 후보 manifest/파일 해시 검증 후 후보 OwnerBridge 자체를 별도 패키지 이름으로 로드한다. 검토한 vendor owner 모듈·SDK·실물 드라이버는 import/실행하지 않는다. 별도의 가짜 소유 스레드와 loopback Zenoh peer 두 개가 임시 이름으로 통신한다. 제어 콜백에서 모터 I/O가 발생하지 않는지, 유지 확인 전 재개 차단, 대기 목표 폐기, 오래된 명령 거부, 실행 중 가짜 I/O 완료를 기다리지 않는 정지 접수를 확인한다.

클라우드에서 eclipse-zenoh 1.10.2로 5개 시나리오 통과. 전체 테스트 133개 실행, 2개 건너뜀. stop_rpc_seconds는 loopback 가짜 장비의 요청 왕복 시간이며 실물 로봇 정지 시간이나 최악 지연 보장이 아니다. 사용자 컨테이너의 라이브러리 버전에서 동일 시험이 필요하며 새 패키지 설치·Studio 재시작 없이 임시 폴더에 시험 파일과 후보만 복사한다. 해당 시험은 초기 토크 ON·실물 유지·안전 Home 경로·직원 화면·네트워크 손실 후 처리 검증을 대체하지 않는다.

## 2026-11-04 사용자 Zenoh 통신 통과 및 4/5 준비

사용자 컨테이너 eclipse-zenoh 1.9.0에서 ZENOH_FAKE_ROBOT_OK, hardware_connected=false, installed_files_changed=false를 확인했다. stop_rpc_seconds=0.0002564169990364462는 가짜 장비 통신 왕복 측정으로 실물 정지 성능에 사용하지 않는다. 기존 a4add9de 후보를 이어서 사용하며 보정/모의 시험을 다시 시작하지 않는다.

적용·복원 관리자와 Windows 준비 실행기, 상태·정지 전용 화면을 추가했다. 사용 순서와 한계는 docs/progress/robot-owner-trial-guide.md를 따른다. 현재 단계는 원본 백업/적용과 실물 조작 화면 준비이며 실제 연결/이동은 아직 하지 않는다. 기존 보정값과 후보 코드는 바꾸지 않았다. Home 구현이나 로봇 전체 제어 통합 완료로 보고하지 않는다.

## 2026-11-04 기존 로봇 작업 재개 — 토크 ON 전 목표값 점검 준비

구매품목 완료 기록 후 사용자가 로봇 작업 재개를 요청했다. 기존 보정·적용 후보·Zenoh 검증 결과를 보존한다. 원본 SO101 connect에서 현재 목표 정렬 전 follower 토크가 켜지는 순서를 확인해 tools/robot_start_preflight.py와 기존 실행기의 preflight 명령을 추가했다. 사용자의 실제 점검 실행 결과는 아직 없다. 이 코드는 토크 OFF 상태의 raw 목표 레지스터만 선택적으로 정렬하며 토크 ON·보정 쓰기·Studio 연결은 수행하지 않는다. 전체 시험 151개 실행, 2개 건너뜀; 새 점검 모의 시험 5개 통과. Home·이동 중 실제 정지·시작 시 토크 ON 성능은 여전히 미검증이다.

## 2026-11-04 목표값 동기화 후 토크 검증 실패와 후속 관측

사용자 읽기 점검에서 보정 일치·6관절 토크 OFF를 확인했고 기존 Goal_Position과 현재 위치가 달랐다(맨 아래 회전 -172 ticks, 집게 +692 ticks 등). --sync-goal 실행은 목표 기록 후 shoulder_pan 토크 OFF 검증에서 실패했다. 실패 당시 실제 반환값과 다른 관절 상태는 수집되지 않아 토크 변화의 원인은 미확정이다. 쓰기 함수 write/_write와 직렬화 함수를 사용자 환경에서 읽었으나 해당 코드에는 명시적인 토크 ON 처리가 없다. 레지스터 주소는 Torque_Enable=40(1byte), Goal_Position=42(2byte), Present_Position=56(2byte)로 서로 겹치지 않는다. 펌웨어 동작·동시 접근·통신 반환값 등을 원인으로 단정하거나 확인 없이 라이브러리를 변경하지 않는다.

후속 읽기에서 6관절 토크=0 및 목표=현재 raw 위치를 확인했다: shoulder_pan 2133, shoulder_lift 853, elbow_flex 3060, wrist_flex 2966, wrist_roll 2048, gripper 1351. 이어 사용자 safeOff에서도 전 관절 0, errors=[], TORQUE_OFF_VERIFIED를 확인했다. 앞선 실패가 해결되었다거나 처음부터 오검출이었다고 판단하지 않는다. 목표값 쓰기를 반복하지 않고 사용자 받침·자세 유지·빈 집게와 보이는 정지 화면을 전제로 연결/유지/정지 요청의 제한된 실물 시험을 준비한다. 연결 시 토크 ON은 실제 하드웨어 상태 변경이며 이후 사용자 실행 결과는 아직 없다. 이동 중 정지·Home 검증 완료가 아니다.

## 2026-11-04 실물 연결·정지 요청 확인, 제한 이동 시험 준비

사용자가 Studio 팔로워 Session hold와 Connect ON 화면을 제공했고 별도 정지 화면에서 버튼 두 번 뒤 명령 세대 2, 유지 명령 전송 완료를 확인했다. 추가 질문에서 실제 팔이 가만히 있고 집게가 비어 있음을 확인했다. 정지 버튼이 실제 소유자에 전달되는 단계까지 확인한 것이며 움직이는 팔의 정지 완료로 확대하지 않는다.

현재 연결을 유지하는 move-test 실행기와 tools/robot_bounded_stop_trial.py를 추가했다. 카운트다운 중 정지는 이동 취소, 이동 중 외부 정지 관측 시 이후 목표 차단, 제한 경로 종료/오류 시 종료 정지 시도, 자동 복귀 없음, 현재 위치 대비 맨 아래 회전 최대 +1 정규화 단위 제한이다. 기존 정지 패치와 보정은 변경하지 않았다. 전체 157개 시험 실행, 2개 건너뜀. 가짜 장비를 사용하는 실제 Zenoh 시험에서 8번째 이동 요청에 외부 정지를 주어 7개 목표 전송 후 나머지 목표가 차단됨과 이후 관측 위치 일정성을 확인했다. 실제 장비로 이동 중 정지한 결과는 아직 없다.

## 2026-11-04 제한 이동 중 실물 수동 정지 결과

사용자가 실제 팔의 작은 움직임을 보고 정지 버튼을 눌렀다고 보고했다. 실행 결과 MANUAL_STOP_OBSERVED, sent_targets=51(최대 60), max_observed_delta_normalized=0.5171775817871094, stop_requested_after_trial=true, hold_commanded_after_trial=true를 확인했다. shoulder_pan은 시작 -4.322127819061279에서 최종 -3.8788325786590576으로 관측됐고, 나머지 5관절의 시작/최종 값은 같았다. 정지 후 약 0.5초간 관측한 6관절의 post_stop_span_normalized는 모두 0.0이었다. automatic_return=false로 자동 복귀는 수행하지 않았다.

이 결과는 현재 배치에서 맨 아래 좌우 회전 관절의 제한된 저속 이동 중 수동 정지 요청/후속 목표 차단/유지 명령/짧은 관측 구간의 위치 일정성을 확인한 것이다. 버튼 클릭 시각과 물리 정지 시각을 계측한 결과가 아니며 즉시 정지 최악 지연, 모든 관절/집기/모델/VLA 동작 중 정지를 보장하지 않는다. LF-12 전체나 Home 완료로 표시하지 않는다.

다음 Home 준비로 tools/robot_home_snapshot.py와 기존 실행기의 capture-home을 추가했다. 기존 소유자에 status 요청과 상태 구독만 수행하고 현재 자세를 후보로 저장한다. candidate_only=true, home_approved=false, path_verified=false를 명시하며 현재 보드 보정을 새로 확인한 것으로 표현하지 않는다. 사용자 자세/경로 승인 없이 이 후보를 Home 목표로 자동 실행하지 않는다. 전체 163개 시험 실행, 2개 건너뜀; 새 읽기 전용/상태 변화/기존 파일 보존 모의 시험 6개 통과. 사용자 후보 저장 결과는 아직 없다.

## 2026-11-04 접힌 자세 Home 목표 선정 및 변경 가능한 설정

사용자가 저장한 접힌 자세를 Home 목표로 지정하고 추후 편한 자세 변경 기능을 요청했다. 후보의 6관절 값을 robot/config/home_pose.json 기본 설정에 반영했다. robot/home_profiles.py와 tools/configure_robot_home.py는 후보 선택·장비/단위/보정 해시 검증·버전·이력·원자적 활성 설정 교체를 제공한다. 로컬 설정은 outputs/robot-home/active.json으로 분리해 git pull과 구분하고, 이전 설정은 history에 보존한다.

Home 목표 선택은 완료됐지만 복귀 경로 검증 및 실행은 아직 미완료라 path_verified=false, motion_enabled=false를 유지한다. 자세가 바뀌어도 이전 경로를 재사용하지 않으며 편한 설정 화면은 docs/design/robot-home-settings.md에 후속 요구로 기록했다. 기존 정지 화면·소유자 패치·보정값은 변경하지 않았다. 전체 시험 170개 실행, 2개 건너뜀; 새 설정 교체·이력·잘못된 장비/보정/값 차단·잠금·파일 실패 보존 시험 7개 통과. 사용자 PC의 활성 설정 저장 결과는 후속 확인한다.

## 2026-11-04 근거리 Home 실행과 화면/중단 시험 준비 완료

사용자가 정상 출력을 기다리며 다음 구현을 끊지 말라고 지시했다. 기존 후보/보정/소유자 패치를 변경하지 않고 tools/robot_home_return.py와 화면 Home 버튼을 연결했다. Home 목표 근처의 맨 아래 회전만 최대 1 정규화 단위로 제한 복귀하며, 다른 관절이 목표의 0.2단위 밖이면 실행하지 않는다. 일반 복귀 경로 승인/실행 활성화와 분리한 실험 경로다.

직원 확인, 세션/세대 고정, 시작 전 정지/유지 상태, 중복 시작 거부, 별도 정지 통신, Home 도중 정지 시 재시작 없음, 오류 시 종료 정지 시도를 구현했다. 이미 Home이면 재개나 이동 없이 반환한다. 다른 관절/집게는 출발 시 측정 위치를 유지한다. Home 초기 거부는 다른 진행 작업을 임의 정지시키지 않는다. 조작 화면은 현재 Home 이름·버전을 읽고, Home 중에도 정지 버튼을 유지한다. 모델/VLA 및 공통 관제탑 backend 연결은 이번 변경에 포함하지 않았다.

모의/HTTP 180개 시험 실행, 2개 건너뜀. 실제 Zenoh와 가짜 장비 및 실제 화면용 작업자에서 정상 Home와 복귀 중 정지를 확인했다. 사용자 PC에서는 패널만 갱신한 뒤 이미 Home 확인→제한 이동 후 복귀→다시 제한 이동 후 복귀 중 정지를 연속 진행하도록 안내한다. 실물 Home 결과 확인과 일반 작업 공간의 복귀 경로는 남아 있다.
