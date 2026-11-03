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
