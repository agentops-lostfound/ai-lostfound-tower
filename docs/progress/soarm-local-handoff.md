# SO ARM 로컬 구축·보정 인계

기록일: 2026-11-03 (한국 시간)

별도 로컬 작업 채팅에서 전달받은 실행 결과다. 이 클라우드에서 장비·파일·API를 재검증하지 않았다. 아래 기록은 새 구동·재보정·녹화·학습 실행 지시가 아니다. 사용자 Windows와 클라우드의 localhost·파일시스템을 구분한다.

## 환경과 현재 장비

- Windows 11, RAM 16GB, RTX 3050 6GB. 작업 폴더 `C:\00lsp\T_prj_edge`.
- WSL2 Ubuntu-24.04, 메모리 10GB·스왑 12GB. 소스 `/home/user/physical-ai-studio`, Docker 작업 위치 `application/docker`.
- 컨테이너 `physical-ai-studio-cuda`, 볼륨 `docker_physical-ai-studio-storage`, Studio `http://localhost:7860`. PyTorch 2.11.0+cu128에서 GPU 인식 보고.
- 새 리더 SO101: 시리얼 `5B91045573`, 약 5.3V, 당시 COM7.
- 새 팔로워 SO101: 시리얼 `5B91030622`, 약 12.2~12.3V, 당시 COM4.
- 보드 VID:PID `1a86:55d3`. COM/BUSID 대신 시리얼로 식별. Linux 포트는 `/dev/serial/by-id/usb-1a86_USB_Single_Serial_<시리얼>-if00`.
- 이전 리더 `5B3D044199`·팔로워 `5B3D044791`와 프로젝트 `so101_pickplace`는 보존.

새 Studio 프로젝트 `so101_new_pair` ID `21aaf3e7-e56c-428f-8687-60b7ef0932ae`, 환경 `new_pair_teleop` ID `804206d9-50a8-48ba-a6a2-ae0310db60a2`. 리더 로봇 ID `ee109274-b873-4401-a8dd-10cbafd7e537`, 팔로워 ID `0f876b83-64cd-4bb9-9630-963eaeb3c0b7`.

## 최종 보정값 — 과거 중간값과 구분

모든 drive_mode=0. 아래 값은 로컬 인계의 최종값이며 보드 읽기와 비교하지 않고 재적용하지 않는다.

| 아래부터 관절·ID | 리더 homing / min / max | 팔로워 homing / min / max |
| --- | --- | --- |
| 1 좌우 회전 shoulder_pan | -2008 / 776 / 3427 | 1553 / 846 / 3553 |
| 2 앞뒤 숙임 shoulder_lift | -878 / 863 / 3230 | 234 / 849 / 3211 |
| 3 두 긴 팔 접힘 elbow_flex | 539 / 810 / 3121 | -1420 / 877 / 3063 |
| 4 끝부분 위아래 wrist_flex | -1272 / 874 / 2643 | 899 / 975 / 2967 |
| 5 끝부분 회전 wrist_roll | 1468 / 0 / 4095 | 1876 / 137 / 3933 |
| 6 트리거·집게 gripper | 825 / 1371 / 2699 | -1417 / 1345 / 2800 |

팔로워 스티커 조립 순서와 달리 실제 통신 ID는 1~6 정상 대응을 개별 움직임으로 확인해 재할당·재배선하지 않았다. 리더는 일부 범위 측정에서 인접 관절도 움직였지만 이후 사용자 텔레오퍼레이션 확인이 있었다.

- 5번 리더 offset은 519→1468로 보정. 리더 full-turn 범위 0~4095, 팔로워는 측정한 137~3933 유지. 보정 후 정규화 약 1.25/1.26 일치 보고.
- 4번은 리더 손잡이의 책상 접촉 끝과 팔로워 집게의 작업면 끝을 대응시켰다. 최종 max는 리더 2643, 팔로워 2967. 직후 양쪽 100.0, 이후 시작 전 비교는 100.0/99.9 보고.
- 이 끝점 대응은 다른 관절 자세에서의 바닥 충돌 방지나 소프트 스타트·자동 자세 정렬 구현이 아니다.

## 완료 보고와 남은 검증

토크 OFF 수동 중앙 자세·범위 측정 후 보드 저장/읽기 확인, Studio·최종 JSON 갱신을 보고받았다. 반복 15초 제한 텔레오퍼레이션에서 약 445~447 observation, 정상 종료 및 사용자의 자연스러운 추종 확인이 있었다. 테스트 종료 시 hold·disconnect·session stop을 사용했다. 5·6번 떨림은 재테스트 후 괜찮다는 사용자 확인이 있었고 임의 PID·토크 튜닝은 하지 않았다.

초기 연결에서 리더 연속 읽기 실패가 있었고, 보드에서 이전 보정값이 한 번 읽힌 이력도 있다. 이후 재적용·일치 확인을 했으나 원인은 미확정이며 전원 재인가·재부팅 후 유지 검증은 남아 있다. 이전 순간 API 상태를 현재 상태로 가정하지 않는다.

다음 구동 전 실제 로컬 도구로 현재 세션·보드 read_calibration·Studio payload·자세 차이와 사용자에게 보이는 조작 화면을 확인한다. 시작 자세 차이가 크면 ON 순간 움직일 수 있다. Teleoperate OFF·세션 종료·USB 해제는 토크 OFF와 다르다. 팔로워 disconnect 후 토크 유지 구현이며 토크 해제 시 팔을 받친다. JSON torque 필드는 과거 스냅샷일 뿐이다.

## 카메라·녹화 준비

- 카메라 icspring VID:PID `32e6:9211`은 Windows에 유지하며 usbipd attach 대상이 아니다.
- 자체 작성 MJPEG 브리지: Windows `127.0.0.1:8765`, 640×480·30fps. Studio 주소 `http://host.docker.internal:8765/camera.mjpg`.
- Windows Python 3.12, OpenCV headless 4.12.0.88·NumPy 2.2.6. Windows·컨테이너에서 영상 수신 및 health frames 증가·error=null 확인 보고.
- 이전 프로젝트에는 cam 등록. **새 프로젝트·환경의 cameras는 비어 있어 추가가 필요하다.** 브리지 정상만으로 영상 포함 녹화 준비 완료가 아니다.
- LeRobot 0.6.0의 RGB-only 녹화에서 불필요한 depth encoder 초기화 오류를 재현해 depth 키가 있을 때만 생성하도록 로컬 패치. RGB 30프레임 인코딩·디코딩 시험 통과 보고. 패치 위치 `/app/storage/patches/lerobot-lazy-depth/`. 버전 변경 시 재검토하며 컨테이너 재생성 후 유지 여부 확인.

## 로컬 파일·보존

설정·도구는 `C:\00lsp\T_prj_edge\soarm-setup`, 백업은 `soarm-backup`에 있다. 최종 기준은 `new-leader-calibration-complete.json`, `new-follower-calibration-complete.json` 및 백업의 `new-leader-floor-endpoint-calibrated.json`, `new-follower-floor-endpoint-calibrated.json`이다. 중간 calibrated/before-* 파일로 되돌리지 않는다.

주요 도구는 `compare_new_pair_calibration.py`(읽기 비교), `test_new_pair_teleop.py`(15초 실제 구동), `start-studio.ps1`, `start-camera.ps1`, `check-status.ps1`, `usbipd-autoattach.ps1`, `patch_rgb_recording.py`, `test_rgb_recording.py`다. 파일명만 보고 일괄 실행하지 않는다. 컨테이너 /tmp 파일은 영구 기준이 아니다.

바탕화면 Studio 바로가기는 Docker·USB 자동 연결·패치·브리지 준비 후 페이지를 열며 Teleoperate/모델 추론을 자동 시작하지 않는다. USB 작업 `soarm-usb-autoattach`는 이전·새 로봇 네 시리얼을 대상으로 하며 카메라는 제외한다. 재부팅 자동 시작 검증은 남았다.

초기 이미지 tar.gz 약 5.94GB는 gzip 무결성 확인 보고이나 새 프로젝트·런타임 패치 전체의 최신 스냅샷은 아니다. 초기 DB 백업도 새 프로젝트 이전이다. 새 프로젝트 포함 DB 전체 백업과 향후 데이터셋·모델 백업이 필요하다. `docker compose down -v`로 볼륨을 삭제하지 않는다. 이 기록에는 실제 로컬 JSON·패치·백업 파일을 첨부하거나 복원하지 않았다.

## 다음 작업

1. 사용자에게 보이는 새 프로젝트 화면·현재 상태·보정값·자세를 읽기 확인.
2. 재시작 후 보정 유지·USB·카메라 자동 준비 확인 및 최신 DB 백업.
3. 새 환경에 카메라 추가, 작업·성공 기준·카메라/조명/바닥 배치 확정.
4. 성공 시연 녹화와 영상·관절 데이터 검증 후 학습 진행. 실제 작업 데이터 녹화·학습·자율 추론은 아직 미실행.
5. 인계 제안은 RTX 3050 6GB·RAM 16GB에서 Data Workers=2, 녹화/학습 동시 실행 회피, ACT 시작 검토다. 프로젝트에서 고려 중인 SmolVLA를 대체 확정한 것은 아니다.

물리 조작 안내는 아래부터 1~6번으로 설명하고 사용자의 준비 확인에 맞춰 한 단계씩 진행한다. 완료된 초기 구축을 처음부터 다시 수행하지 않는다.
