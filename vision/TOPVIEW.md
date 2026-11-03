# 탑뷰 YOLO + ArUco 추론 (LF-3)

기존 촬영·학습 코드에 단일 이미지 추론 모듈을 추가했습니다. Qwen/OCR/로봇은 호출하지 않습니다.

## 구성과 기존 코드의 관계

- `yolo/detector.py`, `cropper.py`: YOLO 검출, 원본 bbox 중심, crop 저장
- `aruco/detector.py`, `calibration.py`: 같은 원본 프레임에서 마커 검출, 실측 대응점 homography, mm 좌표 변환
- `vision_pipeline.py`: 통합 JSON과 디버그 이미지 저장
- `scripts/test_vision.py`: 이미지 입력 CLI와 CUDA/버전 확인
- `configs/vision.yaml`: 추론 모델·마커 좌표·출력 설정
- `configs/data_six_class.example.yaml`: 별도 6종 실험용 데이터셋 예시
- `../tests/test_topview_vision.py`: 합성 마커·보정 실패·crop·통합 데이터 흐름 시험

기존 `config.py`, 촬영·데이터 준비·학습 스크립트의 4종 클래스 순서는 유지합니다. `phone/usb/lip_balm/hand_cream/card_wallet/power_bank` 6종 예시는 기존 `wallet/usb/lipbalm/phone` 라벨과 호환되지 않습니다. 기존 라벨을 재해석하거나 기존 학습 스크립트에 그대로 입력하지 마세요. 6종 학습에는 별도 데이터·클래스 합의와 학습 코드 대응이 필요합니다.

## Windows 실행

clone한 저장소 루트에서 Python 3.11로 전용 환경을 생성합니다. 기존 Qwen 환경은 변경하지 않습니다.

```powershell
py -3.11 -m venv .venv-vision
.\.venv-vision\Scripts\python.exe -m pip install -r vision/requirements_inference.txt
.\.venv-vision\Scripts\python.exe -m vision.scripts.test_vision --check-environment
.\.venv-vision\Scripts\python.exe -m vision.scripts.test_vision --image "C:\photos\topview.jpg" --device cpu
.\.venv-vision\Scripts\python.exe -m vision.scripts.test_vision --image "C:\photos\topview.jpg" --device 0
.\.venv-vision\Scripts\python.exe -m vision.scripts.test_vision --image "C:\photos\topview.jpg" --aruco-only
.\.venv-vision\Scripts\python.exe -m unittest discover -s tests
```

`requirements_inference.txt`는 검증한 추론 의존성을 고정한 최소 설치 파일입니다. 기존 `vision/requirements.txt`는 학습·내보내기 의존성을 유지하며 YAML 의존성만 추가했습니다. 이미 구성된 팀 환경의 torch를 바꾸기 전에 별도 환경에서 검증하세요.

`auto`는 torch.cuda.is_available()에 따라 장치를 선택합니다. 현재 검증 환경은 torch 2.9.1+cpu여서 GPU는 사용하지 않았습니다. CUDA 실행에는 [PyTorch 공식 안내](https://pytorch.org/get-started/locally/)에 맞는 torch/torchvision wheel을 비전 환경에 설치해야 합니다.

WSL2에서는 Windows 가상환경을 복사하지 않고 `python3.11 -m venv .venv-vision` 후 의존성 파일로 재생성합니다.

## 모델과 경로

기본 `models/yolo26n.pt`는 없으면 Ultralytics의 공식 asset 다운로드 함수를 통해 받습니다. 네트워크가 필요합니다. 커스텀 모델은 자동 다운로드하지 않습니다. 기존 학습 결과를 쓰려면 `configs/vision.yaml`의 `model`을 `models/<학습 이름>/best.pt`로 바꿉니다.

사전학습 모델의 COCO 클래스 이름은 그대로 반환합니다. 임의로 4종/6종 클래스에 매핑하지 않으며 작은 USB·립밤 등 실제 물품의 검출은 보장하지 않습니다.

기본 설정은 `vision/configs/vision.yaml`입니다. `--config`로 다른 파일을 선택합니다. 모델·출력 상대 경로는 설정 파일 위치나 현재 디렉터리가 아닌 **저장소 루트 기준**입니다. 출력은 `outputs/vision/<고유 ID>/result.json`, `debug.jpg`, `crops/object_N.jpg`입니다. 가중치·실사진·가상환경·출력은 커밋하지 않습니다.

## 보정과 결과

`aruco.dictionary`는 인쇄한 마커 사전과 일치시킵니다. `markers_mm` 기본값은 `{}`입니다. 실제 설치 위치가 미정이므로 임의 실측값은 없습니다. 실측 후 마커 ID마다 작업대 평면의 4×2 모서리 좌표(mm)를 입력합니다. 순서는 마커 정규 방향 TL, TR, BR, BL이며 화면상 좌상단 순서로 재정렬하지 않습니다. 원점·축·인쇄 크기·방향을 함께 정의하세요.

4개 이상의 비공선 대응점이 필요합니다. 마커 없음, 대응점 부족, 중복 ID, 퇴화/불안정 변환, 높은 재투영 오차는 실패 상태와 이유를 반환합니다. 단일 마커로 계산은 가능하지만 넓은 작업대는 여러 마커와 별도 실측점으로 정확도를 확인해야 합니다. 오차 임계값 단위는 mm입니다.

객체 배열 `objects`에는 id, class_id, class_name, confidence, bbox(xyxy), center_px, crop_path, center_world_mm, calibration_valid가 있습니다. 중심은 crop 여백 전 bbox에서 계산하며 crop만 이미지 경계로 제한합니다. 유효한 보정이 없으면 실좌표는 null입니다. CLI 종료 코드 0은 처리 완료이며 좌표 보정 성공을 뜻하지 않습니다. ArUco-only 모드는 YOLO를 생략합니다.

`vision.vision_pipeline.run_image()`는 `(report, json_path)`를 반환합니다. 이는 Qwen에 crop과 좌표를 전달하기 위한 중간 검출 결과입니다. 기존 `agents/contracts.py`의 특징 분석 결과와는 별도 형식이며 공통 계약은 변경하지 않았습니다. 향후 Qwen 결과를 받은 뒤 명시적 어댑터로 결합해야 합니다. 클래스 이름이나 색상·문자 특징을 임의 생성하지 않습니다.

렌즈 왜곡 보정은 미구현입니다. 필요하면 두 검출기에 동일한 보정 프레임을 전달해야 합니다. 물체 높이에 따른 시차, bbox 중심과 파지점 차이, 작업대→로봇 좌표 변환은 별도 검증이 필요합니다.

검증 내용은 [TOPVIEW_VALIDATION.md](TOPVIEW_VALIDATION.md)를 참고하세요.
