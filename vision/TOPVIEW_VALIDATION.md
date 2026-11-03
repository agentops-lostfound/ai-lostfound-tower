# LF-3 탑뷰 추론 통합 검증

기준: main 6f1c002에서 분기한 LF-3-yolo-aruco. 기존 촬영·데이터 준비·학습 코드와 4종 클래스 설정, 팀 공통 contracts는 변경하지 않았습니다.

## 검증

- `python -m unittest discover -s tests`: 134개 실행, 실패/오류 0개, DB 실연결 시험 1개 건너뜀(LF_TEST_DSN 미설정).
- 신규 5개 시험: 합성 마커 ID 7 검출·합성 좌표 변환, 보정 실패 시 null, 모순/준퇴화 대응점 거부, crop 경계·여백, 원본 프레임 공유 및 bbox 중심 유지와 JSON·이미지 저장.
- 실제 YOLO26n CPU 추론: Ultralytics 패키지 bus.jpg에서 bus 1개·person 4개 검출, crop 5개와 result.json/debug.jpg 저장. 실제 촬영 물품의 성능 평가가 아닌 배선 검증입니다.
- 새 위치의 CLI `python -m vision.scripts.test_vision`와 환경 확인 정상 동작.
- Python 3.11.18, Ultralytics 8.4.199, OpenCV Python 4.14.0.94, NumPy 2.4.6, PyYAML 6.0.3, torch 2.9.1+cpu, torchvision 0.24.1.
- NVIDIA RTX 3050 6GB가 있는 PC지만 검증용 PyTorch는 CPU wheel. CUDA 추론 미검증.

## 남은 현장 검증

실제 탑뷰 물품 사진과 정답 라벨을 통한 성능 평가, 인쇄 마커 ID·사전·크기·방향·작업대 모서리 mm 좌표 실측이 필요합니다. 실측 설정은 비어 있으며 실제 작업대 좌표의 정확도는 미검증입니다. 합성 mm 좌표는 수학적 동작 시험일 뿐입니다. 렌즈 왜곡, 높이 시차, 로봇 좌표 변환도 별도 검증 대상입니다.

Qwen/OCR/로봇은 호출하지 않았습니다. Qwen 코드를 포함하지 않았으며 기존 로컬 Qwen 환경과 코드는 유지했습니다. 가중치·사진·가상환경·실행 결과는 Git 추적 대상에서 제외했습니다.

## 사진부터 Qwen까지 연속 실행 검증

단일 CLI `python -m vision.scripts.run_sequence`로 실제 로컬 topview.jpg를 입력해 YOLO CPU 검출→crop 2개→Qwen GPU 추출→통합 JSON 기록을 완료했습니다. 최종 sequence.status=complete, qwen_failed=0. 전체 약 49.1초(프로세스 시작·모델 로딩·이미지/JSON 저장 포함), YOLO/ArUco 단계 약 4.9초였습니다.

전체 unittest 137개 실행: 실패/오류 없음, 실제 DB 시험 1개 건너뜀. 신규 시험은 검출 0개 시 Qwen 생략, Qwen 시작 실패 시 검출 보존과 null 특징, 정상 결과의 물체 ID 연결을 확인합니다. 실제 실행에서도 각 crop·특징 파일 존재와 JSON 검증 성공, 보정 미설정 시 null 좌표를 확인했습니다.

이는 연결 동작 검증입니다. 기존 지갑 중심 Qwen 출력 스키마를 유지했으며 시각적 정확도는 별도 검증 대상입니다. 원본·결과 사진, JSON, 로그는 outputs/에만 저장하고 추적하지 않습니다.

## general_items_v1 검증

일반 물품용 출력(category: phone/usb/lip_balm/wallet/card_wallet/hand_cream/power_bank/other/unknown)을 추가했습니다. 지갑 전용 wallet_type은 제거하고 crop의 시각 정보만 사용합니다. 외부 Qwen 소스·환경·가중치는 유지했으며 추가 학습은 하지 않았습니다.

초기 JSON Schema 제시 방식에서 모델이 스키마 구조를 결과로 복제하는 실패가 발생했습니다. 실패 원문을 로그로 보존하고, 평평한 JSON 템플릿과 정확한 키 목록을 제시하도록 수정했습니다. 결과를 임의 변환하지 않았습니다.

전체 unittest 142개 실행, 실패/오류 0개, DB 시험 1개 건너뜀. 범용 품목 허용, 지갑 전용 필드 및 중복 키 거부, 자료형·스티커 일관성·코드펜스 처리를 검사했습니다.

현재 topview.jpg(스마트폰 2개 사진)로 최종 전체 시퀀스 정상 완료: qwen_failed=0, 전체 약 51.5초, YOLO 단계 약 4.2초. 각 crop의 품목과 특징 JSON을 저장했습니다. 이는 이 사진에서의 연결 확인이며 USB·립밤·핸드크림 등 전체 품목 성능과 재질/문자 정확도는 미검증입니다. 기존 검출기와 팀 4종 학습 설정 및 공통 contracts는 변경하지 않았습니다.
