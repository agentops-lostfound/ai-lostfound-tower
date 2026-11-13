# AI 분실물 관제탑 — 독립 비전 모듈

기존 qwen/ 코드·가중치·환경은 수정하지 않았습니다. Python 3.11을 권장합니다. 프로젝트 루트는 현재 Git 저장소가 아닙니다.

## Windows 실행

프로젝트 루트 PowerShell에서 실행합니다. 시스템 Python 3.15 대신 3.11을 사용합니다.

```powershell
py -3.11 -m venv .venv-vision
# 현재 PC에서는 다음 기존 Python 바이너리로 생성 가능:
# & .\qwen\.python\cpython-3.11.18-windows-x86_64-none\python.exe -m venv .venv-vision
.\.venv-vision\Scripts\python.exe -m pip install -r requirements_vision.txt
.\.venv-vision\Scripts\python.exe -m scripts.test_vision --check-environment
.\.venv-vision\Scripts\python.exe -m scripts.test_vision --image "C:\photos\topview.jpg" --device cpu
.\.venv-vision\Scripts\python.exe -m scripts.test_vision --image "C:\photos\topview.jpg" --device 0
.\.venv-vision\Scripts\python.exe -m scripts.test_vision --image "C:\photos\topview.jpg" --aruco-only
.\.venv-vision\Scripts\python.exe -m unittest discover -s tests -v
```

기본 device=auto는 torch.cuda.is_available()로 장치를 선택합니다. NVIDIA GPU가 있어도 CPU wheel이면 CPU로 실행합니다. GPU가 필요하면 [PyTorch 공식 설치 안내](https://pytorch.org/get-started/locally/)에 맞는 torch/torchvision 조합을 비전 환경에만 설치하세요.

configs/vision.yaml에서 모델·임계값·crop 여백·출력 경로를 변경하고 --config로 다른 설정을 선택합니다. 모델과 출력 상대 경로는 프로젝트 루트 기준입니다. 처음 yolo26n.pt가 없으면 Ultralytics 공식 asset 다운로드 함수를 호출하며 네트워크가 필요합니다. 커스텀 best.pt는 자동 다운로드하지 않습니다.

각 실행은 outputs/<고유 ID>/에 result.json, debug.jpg, crops/object_N.jpg를 저장합니다. JSON의 objects는 객체 배열이며 bbox는 원본 float xyxy, center_px는 여백 추가 전 bbox 중심입니다. crop 범위만 이미지 경계로 제한합니다. ArUco-only 모드는 YOLO를 생략하며 torch를 불러오지 않습니다.

## ArUco 설정과 좌표

YOLO와 ArUco는 같은 원본 BGR 프레임을 처리합니다. dictionary는 인쇄 마커와 일치해야 합니다. markers_mm={}는 실측 미입력 상태이므로 보정 실패가 정상입니다.

실측 후 markers_mm에 마커 ID별 4×2 좌표 배열(mm)을 입력합니다. 순서는 마커 정규 방향 TL, TR, BR, BL이며 이미지 화면의 좌상단 순서로 재정렬하지 않습니다. 작업대 원점, 축 방향, 마커 방향, 실제 인쇄 크기를 정의하고 각 모서리를 동일 평면 좌표계에서 측정하세요. 임의의 실측 예시는 제공하지 않습니다.

비공선 대응점이 4개 이상 필요합니다. 단일 마커로도 수학적 계산은 가능하지만 넓은 작업대에서는 떨어진 여러 마커와 별도 실측점으로 오차를 검증하세요. 마커 없음, 대응점 부족, 중복 ID, 퇴화 행렬, 높은 재투영 오차는 calibration.valid=false와 reason을 반환합니다. 객체의 center_world_mm은 null, calibration_valid는 false입니다. CLI 종료 코드 0은 처리 완료를 뜻하며 좌표 보정 성공을 보장하지 않습니다.

오차 임계값 단위는 mm입니다. 재투영 검사는 실제 정확도 인증이 아닙니다. 렌즈 왜곡 보정은 미구현이며 필요하면 카메라 내부 파라미터로 보정한 동일 프레임을 두 검출기에 전달하세요. 물체 높이의 시차, bbox 중심과 파지점 차이, 작업대→로봇 좌표 변환은 별도 검증 대상입니다.

## 커스텀 학습 준비

YOLO26n은 COCO 클래스 이름을 그대로 반환합니다(예: cell phone). 6개 커스텀 클래스로 임의 매핑하지 않습니다. 작은 USB·립밤 등 실제 11개 물품의 검출은 보장하지 않습니다.

configs/data.yaml은 학습 전용 예시입니다. datasets/lostfound/ 아래 images/train, images/val, images/test 및 labels/train, labels/val, labels/test를 만들고 이미지와 같은 이름의 정규화 YOLO txt 라벨(class cx cy width height)을 준비합니다. 클래스는 phone, usb, lip_balm, hand_cream, card_wallet, power_bank이고 물품 수는 3/1/3/2/1/1입니다. 촬영 세션·조명·배치별로 분할해 유사 이미지의 train/val 누출을 피하세요. 학습 후 model을 best.pt 경로로 교체합니다.

## WSL2 및 Qwen 연결

Windows 가상환경을 복사하지 않습니다. Ubuntu에서 python3.11 -m venv .venv-vision 후 의존성 파일로 재생성합니다. GPU는 WSL2 NVIDIA 드라이버와 CUDA 지원 PyTorch를 확인하세요.

vision_pipeline.run_image()는 (report, json_path)를 반환합니다. 향후 Qwen 전용 프로세스에 객체 ID, crop_path, center_px, center_world_mm, calibration_valid를 JSON으로 전달합니다. 현재 Qwen/OCR/로봇은 호출하지 않습니다. 6GB GPU에서는 모델을 순차 실행하는 방식을 권장합니다.

공식 문서: [YOLO26](https://docs.ultralytics.com/models/yolo26/), [OpenCV ArUco](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html). 생성 파일과 설치 버전, 검증 결과는 VALIDATION_VISION.md를 참고하세요.

전체 설치 목록은 requirements_vision.lock.txt에 기록했습니다(Windows CPU 검증 환경). 주요 의존성은 requirements_vision.txt에 고정되어 있습니다. 현재 설치는 CPU PyTorch이며 CUDA 추론은 별도 CUDA wheel 설치 후 검증이 필요합니다.
