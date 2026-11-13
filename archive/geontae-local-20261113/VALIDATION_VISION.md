# Vision validation — 2026-11-03

## 조사 및 변경 범위

- 루트에는 기존 qwen/만 있었고 루트 Git 저장소 및 main.py는 없었습니다.
- Qwen: Python 3.11.18, torch 2.9.1+cu128, torchvision 0.24.1+cu128, transformers 4.57.6(requirements 기준). 가상환경 설정에는 이전 C:\Users\user\qwen 경로가 남아 있습니다. 수정하지 않았습니다.
- 시스템 Python은 3.15.2. 기존 독립 Python 3.11.18 바이너리로 새 .venv-vision을 생성했습니다.
- NVIDIA 드라이버가 보고한 GPU: RTX 3050 6144 MiB, driver 610.88.

## 생성 파일

- yolo/__init__.py, detector.py, cropper.py 및 weights/ 디렉터리
- aruco/__init__.py, detector.py, calibration.py
- vision_pipeline.py
- configs/vision.yaml, configs/data.yaml
- scripts/__init__.py, scripts/test_vision.py
- tests/test_vision.py
- requirements_vision.txt, README.md, VALIDATION_VISION.md, .gitignore
- 별도 .venv-vision/ (버전 관리 제외)

## 검증 상태

Python 문법 컴파일 완료. 의존성 설치와 실행 결과는 아래에 추가합니다.

최초 pip 실행은 네트워크 제한(WinError 10013)으로 실패했습니다. 비전 환경에만 설치하도록 범위를 유지해 네트워크 허용 경로로 재시도했습니다.

## 실제 현장에서 필요한 검증

기존 Qwen 입력 이미지에 대한 추론은 배선 확인 용도이며 탑뷰 11개 물품에 대한 검출 성능 평가가 아닙니다. 실제 탑뷰 사진, 조명·가림 조건별 데이터와 정답 라벨이 필요합니다. 마커 ID·사전·인쇄 크기·방향·각 모서리의 작업대 mm 좌표를 실측하고 설정해야 합니다. 실측 정보가 없어 실제 작업대 좌표 정확도는 검증하지 않았습니다. 합성 좌표 테스트는 수학적 동작만 검증합니다.

## 최종 실행 결과

- Python 3.11.18, Ultralytics 8.4.199, OpenCV Python 4.14.0.94(cv2 4.14.0), NumPy 2.4.6, PyYAML 6.0.3.
- torch 2.9.1+cpu, torchvision 0.24.1. torch.cuda.is_available()=false. GPU 장치는 존재하지만 현재 비전 환경은 CPU wheel이므로 GPU 추론은 미검증입니다.
- 주요 패키지는 requirements_vision.txt에 고정했고 전체 설치 목록은 requirements_vision.lock.txt에 기록했습니다. 전체 lock은 Windows CPU 검증 환경의 기록이며 WSL2/CUDA 설치에는 주요 의존성 파일을 사용합니다.
- unittest 4개 모두 통과: 합성 ArUco ID 7 검출 및 합성 mm 좌표 변환, 보정 실패 상태, 모순/준퇴화 대응점 거부, crop 경계·여백. 합성 테스트에는 임시 이미지와 임시 설정을 사용하며 실제 작업대 실측값이 아닙니다.
- pip check: No broken requirements found.
- YOLO26n 공식 가중치 다운로드 성공: https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt (약 5.3MB).
- 기존 Qwen 입력 이미지 01-3_jpg.rf.2c92f3d4c06faa707170580d4bce9f0a.jpg: 객체 0개, 마커 0개. 결과 outputs/dcc1ae9f620c4c809e44eed47d745612/result.json. 미검출을 그대로 기록했습니다.
- Ultralytics에 포함된 bus.jpg: 버스 1개와 사람 4개, 총 5개 검출. outputs/12c457b38c094078a059e89d7379040e/result.json 및 crops/ 5개, debug.jpg 저장 확인. JSON의 각 bbox 중심 계산 일치, crop 이미지 읽기 성공, 디버그 이미지의 박스/중심/라벨을 시각 확인했습니다.
- 두 실사진 모두 마커가 없어 calibration.reason=no_markers, 모든 실좌표는 null입니다. 실제 ArUco 마커 사진 및 실측 기반 보정은 미검증입니다.

## 설치 중 문제와 처리

첫 네트워크 차단은 허용된 설치 경로로 재시도했습니다. 최신 torch 2.15.0 다운로드가 장시간 진행되지 않아 해당 전용 설치 프로세스를 중단한 뒤 torch 2.9.1 / torchvision 0.24.1로 재시도해 설치와 CPU 실행을 완료했습니다. Qwen 환경에는 패키지를 설치하지 않았습니다.

문서 초안은 PowerShell→Python 파이프의 문자 인코딩 때문에 한글이 물음표로 저장된 것을 발견하여 UTF-8 직접 저장으로 교정하고 확인했습니다.
