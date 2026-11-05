# 11/5 Physical AI Studio 설정과 1280×720 비전 시험

## 완료 범위와 근거

설치·실물 검증 항목은 사용자가 전달한 설치 세션 인수인계를 근거로 한다. 이번 세션에서 직접 재확인한 항목과 구분한다.

- 설치 세션: Windows11 + Ubuntu24.04 WSL2 + Docker CUDA, Physical AI Studio0.3.0, PyTorch2.11.0+cu128, LeRobot0.6.0. 컨테이너 healthy 및 RTX3050 CUDA 확인. 기존 프로젝트 Python 환경과 분리했다.
- SO-101 리더5V·팔로워12V. 양팔 모터6/6, 기존 보정 CALIBRATED를 읽어 등록했다. 재보정·모터ID·펌웨어 변경은 하지 않았다. 사용자가 그리퍼와 팔꿈치 작은 움직임의 정상 추종을 확인했다. 전 관절 범위·충돌·XYZ 정확도는 미검증이다.
- Studio 프로젝트 LostFound SO101 Setup / 환경 SO101 Basic Teleop. 탑뷰 USB는 WSL에서1280×720·30fps. 손목 카메라는 WSL 전달 시 영상 깨짐 때문에 Windows DirectShow→HTTP MJPEG 브리지640×480·30fps를 사용한다.
- 손목 브리지 예약 작업 physical-ai-camera-bridge, localhost8765. 영상 publisher가 종료되면 브리지 health만 정상이어도 Studio 영상은 검을 수 있어 publisher 복구가 필요하다. USB 자동 attach는 미구성이다.
- 이번 세션 직접 확인: Studio localhost7860 HTTP200, 손목 브리지 health ok=true 및 frames39261. WSL 내부·예약 작업 조회는 권한으로 미확인. 현재 토크/텔레옵 상태를 조회하거나 변경하지 않았다.

## 저장 탑뷰 사진 시험

설치 시 저장된 topview-wide.jpg에 기존 YOLO26m/CPU/confidence0.25/imgsz640을 적용했다. Studio 실시간 영상 수집 연결 시험은 아니다.

- 원본1280×720. YOLO bbox와 중심은 원본 좌표, 크롭과 ArUco도 같은 원본을 사용한다.
- 보조배터리·지갑2개 bbox 및 크롭 확인. YOLO는 둘 다 cell phone으로 분류했다. 위쪽 립밤은 미검출이다. Qwen은 이번 사진에 실행하지 않았다.
- ArUco ID0/1 두 개, 대응점8개·inlier8개, 최대 재투영 잔차0.456817mm. 해당 사진으로 새 homography를 계산했다. 실제 로봇 위치 오차 측정값이 아니다.
- 로컬 결과 outputs/vision/62b6e6e43b324206b22e3385a710cd31/result.json 및 debug.jpg. 사진·크롭·원본 로그는 Git 제외 상태로 보관한다.

## 다음 단계와 잠정 사항

픽셀→작업대→잠정 설치XYZ 연결은 fec565a에 공유했다. 실제 controller base/TCP와 대조 전이며 고정Z280mm·축 대응은 수정 가능성이 높다. robot_authorized=false를 유지한다.

다음은 설치된 Studio/LeRobot의 관절 읽기·명령 경로와 SO-101 모델/IK 유무 확인이다. 리더 추종 완료는 임의XYZ 이동 완료와 다르다. Studio 연결을 점유한 상태에서 별도 프로그램으로 같은 팔에 중복 연결하지 않는다. 아직 프로젝트의 실제 로봇 이동·집기·VLA 데이터 수집·학습은 수행하지 않았다.

## 실행·복구 위치

WSL 소스 /home/user/physical-ai-studio, 실행 디렉터리 application/docker. `docker compose up -d --no-build`로 기동한다. 볼륨 삭제 명령은 사용하지 않는다.

Windows 설치 기록·보정 백업·복구 스크립트는 사용자 Documents/Codex/2026-11-05/chatgpt-pdf-docs-handoff-2026-11-2/outputs에 있다. 브리지 실행 폴더는 같은 상위 폴더의 work/camera-bridge이며 예약 작업이 참조하므로 임의 이동하지 않는다. 보정 백업·장치별 식별정보·로컬 원본 파일은 이번 공유에 포함하지 않는다.
