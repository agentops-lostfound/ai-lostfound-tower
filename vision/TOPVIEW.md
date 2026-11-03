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

## 사진 → YOLO → Qwen → JSON 한 번에 실행

Qwen은 별도 Python 프로세스로 호출하며, 한 프로세스에서 모든 crop을 순차 처리해 모델을 재사용합니다. 기존 Qwen 소스와 의존성을 변경하지 않습니다. 기본 실행은 YOLO CPU, 기존 Qwen CUDA 설정입니다. 일반 물품용 general_items_v1 스키마를 사용하며 품목·글자·재질의 정확도는 별도 검증해야 합니다.

현재 PC에서 저장소 루트 PowerShell:

```powershell
& ..\.venv-vision\Scripts\python.exe -m vision.scripts.run_sequence `
  --image "C:\Users\user\Pictures\Camera Roll\topview.jpg" `
  --qwen-root "..\qwen" `
  --qwen-python "..\qwen\.python\cpython-3.11.18-windows-x86_64-none\python.exe" `
  --qwen-site-packages "..\qwen\.venv\Lib\site-packages"
```

일반적인 정상 Qwen 가상환경에서는 `--qwen-python`에 그 환경의 python.exe(WSL에서는 bin/python)를 지정하고 `--qwen-site-packages`는 생략합니다. 위 PC는 기존 가상환경의 기본 Python 경로가 이전 폴더를 가리켜 독립 Python에 기존 site-packages를 연결한 것입니다. 환경 파일은 수정하지 않습니다.

Qwen 모델 캐시는 미리 준비되어 있어야 합니다. 이 CLI는 오프라인으로 동작하며 자동 다운로드하지 않습니다. `--config`와 `--device`는 YOLO/ArUco 설정에 적용합니다.

한 실행 폴더에 다음을 기록합니다:

- `result.json`: 원래 YOLO·ArUco 검출 결과
- `crops/`, `debug.jpg`: 검출 crop과 표시 이미지
- `result_with_qwen.json`: 물체 ID·좌표와 `objects[].qwen.features`를 연결한 최종 결과
- `qwen/object_N.json`: 각 물체의 원본 특징 JSON
- `qwen/logs/`: 추론 시간·GPU 정보·검증 실패 원문
- `qwen_process.log`: Qwen 프로세스 표준 출력과 오류

`sequence.status`는 complete/failed/no_detections입니다. complete는 실행과 JSON 스키마 검증 완료를 뜻하며 시각적 정답을 보증하지 않습니다. 개별 물체는 qwen.status=ok/failed와 features 또는 error를 가집니다. 검출 0개면 Qwen을 실행하지 않습니다. 실패 시 CLI 종료 코드는 1이며 성공한 중간 결과는 유지합니다. 실제 mm 좌표는 ArUco 보정이 유효할 때만 반환합니다.

진행 상황은 터미널에 1/3 검출, 2/3 Qwen, 3/3 저장으로 표시합니다. Qwen 대기 중에는 5초마다 완료 crop 수와 경과 시간을 출력합니다. Ctrl+C로 Qwen 단계를 중단하면 자식 프로세스를 종료하고 이미 완료한 특징은 보존하며 미완료 항목과 sequence.status를 cancelled로 저장합니다(종료 코드 130).

## 일반 물품용 Qwen 출력

현재 시퀀스는 `item_features.py`의 `general_items_v1` 프롬프트·스키마를 사용합니다. 기존 외부 Qwen의 모델 로더·전처리·벤치마크 기능만 재사용하며 원본 소스와 가중치는 수정하지 않습니다. 추가 학습은 수행하지 않았습니다.

품목은 phone, usb, lip_balm, wallet, card_wallet, hand_cream, power_bank, other, unknown입니다. 자유 특징 문장은 영어이며 지갑 전용 wallet_type 필드는 없습니다. 색상·형태·재질·읽을 수 있는 글자·스티커·특징을 반환합니다. 불확실한 글자와 재질은 추정하지 않고 빈 배열, 불확실한 형태는 null로 출력하도록 지시합니다. 이 지시는 모델의 환각 방지를 보장하지 않으므로 사진과 대조해 평가하세요.

중복 키·추가 필드·잘못된 자료형·스티커 상태 모순은 검증 실패로 기록하고 기존 재시도 설정에 따라 다시 추론합니다. 최종 실패 시 임의 값으로 보정하지 않습니다. 실행 명령은 동일하며 모델에는 YOLO 클래스 이름을 전달하지 않고 crop만 전달합니다. 검출되지 않은 USB·립밤은 Qwen에 전달되지 않습니다. 기존 팀 공통 agents/contracts.py와는 별도 중간 출력입니다.

## item 1종 검출 학습

탑뷰 검출은 물품 종류 구분 대신 `0: item` 한 종류로 학습합니다. 폰·USB·립밤·지갑·핸드크림·보조배터리마다 개별 박스를 그리고 모든 라벨에 클래스 0을 사용합니다. Qwen의 세부 품목·특징 분류는 유지합니다. COCO 가중치 이름만 item으로 바꾸는 작업은 수행하지 않습니다.

전용 설정은 `vision/configs/data_item.yaml`입니다. 다음 폴더에 실제 사진과 YOLO txt 라벨을 준비하세요. 라벨은 이미지와 동일한 이름이며 한 줄에 `0 cx cy width height`(0~1 정규화 좌표)입니다. 빈 작업대 사진은 빈 라벨 파일로 포함할 수 있지만 양성 사진의 누락 라벨은 반드시 보완하세요. 같은 촬영 세션의 유사 사진이 train/val에 섞이지 않도록 분할합니다. 모든 대상 물품과 조명·방향·배치를 포함하고 일부 사진은 최종 평가용으로 별도 보관하세요.

```text
datasets/lostfound_item/
  images/train/    images/val/
  labels/train/    labels/val/
```

저장소 루트에서 실행:

```powershell
# 설정 확인만 수행 (데이터나 학습 결과를 만들지 않음)
python -m vision.scripts.train_item --dry-run
# 실제 라벨 데이터 준비 후 학습; 현재 비전 환경은 CPU PyTorch
python -m vision.scripts.train_item --epochs 100 --batch 4 --device cpu
# CUDA 학습 환경이 별도로 준비된 경우에만 --device 0 사용
```

기본 시작 모델은 보유한 YOLO26n COCO 가중치입니다. 결과는 `models/item_baseline/best.pt`에 보관하며 같은 출력 폴더가 있으면 새 `--name`을 지정해야 합니다. 기존 팀의 4종 촬영·학습 스크립트와 6종 예시는 변경하지 않습니다. 기존 클래스 라벨 데이터와 이 설정을 혼용하지 마세요.

학습 후 별도 사진에서 미검출·중복 박스·crop 품질을 확인한 뒤, 기존 추론 명령에 `--config vision/configs/vision_item.yaml`을 추가하면 학습한 가중치를 사용합니다. `--name`을 바꿨다면 해당 설정의 model 경로도 맞추세요. 현재 학습용 사진·라벨이 준비되지 않아 실제 학습은 실행하지 않았으며 기본 추론은 COCO 모델을 유지합니다.

## 저장소에 포함된 Qwen 소스 (현재 구성)

이제 외부 프로젝트의 필요한 소스·테스트·의존성이 저장소 `qwen/`에 포함되어 기본 시퀀스 소스로 사용됩니다. 원본은 변경하지 않았습니다. 과거 명령의 `--qwen-root ..\qwen`은 외부 소스를 선택하는 호환 옵션으로 계속 동작합니다. 현재 저장소 소스로 실행하려면 해당 옵션을 생략하고, 기존 캐시를 재사용할 때 `--qwen-cache-dir ..\qwen\.cache\huggingface`를 지정하세요. 새 PC 설치 및 원 개발 PC 명령은 [Qwen 통합 안내](../qwen/INTEGRATION.md)에 정리했습니다. 원본 Qwen README와 VALIDATION은 이전 단독 프로젝트의 기록입니다.
