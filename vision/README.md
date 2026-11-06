# vision

등록기계 내부 AI 카메라 촬영·품목 인식 (LF-3, LF-10). 결과는 고정 항목 JSON(category · color · shape · mark · visible_text · material · confidence).

## 구성
| 파일 | 하는 일 | 실행하는 곳 |
| --- | --- | --- |
| `config.py` | 품목 6종 순서(11/6 고정), 물건 ID·세션·파일 이름 규칙, 예전 이름 연결표 | 공용 |
| `capture_images.py` | 웹캠 촬영 → `품목_물건ID_세션_번호.jpg` + `captures.csv` | 교육원 PC |
| `prepare_dataset.py` | Label Studio YOLO 내보내기 → 세션 단위 train/val + `data.yaml` | 교육원 PC |
| `train_yolo.py` | 받기 → YOLO26 학습 → 검증 → ONNX·OpenVINO 내보내기 → 올리기 → 디스코드 알림 | 집 PC |

## 품목과 물건 ID
| 품목 (클래스 번호) | 이름 | 물건 ID 예 |
| --- | --- | --- |
| 0 | `card_wallet` 지갑 | W01, W02 … |
| 1 | `usb` USB | U01, U02 … |
| 2 | `lip_balm` 립밤 | L01, L02 … |
| 3 | `phone` 모형폰 | P01, P02 |
| 4 | `hand_cream` 핸드크림 | H01, H02 … |
| 5 | `power_bank` 보조배터리 | B01, B02 … |

- **11/6 6종 고정(LF-3).** 클래스 번호 순서는 바꾸지 않는다. 0~3번은 예전 4종(`wallet`·`usb`·`lipbalm`·`phone`)과 같은 번호라 기존 라벨 번호를 그대로 쓴다
- 이름은 Qwen(`vision/item_features.py`)·변환(`agents/vision_adapter.py`)·매칭(`matching/`)과 같은 표기. 한국어는 `agents/contracts.py` CATEGORIES
- 예전 이름 사진(`wallet_W01_s1_000.jpg`, `lipbalm_...`)과 라벨 도구 `classes.txt` 의 예전 이름(`wallet`·`lipbalm`)은 그대로 읽는다(`LEGACY_CLASS_ALIASES`). 새로 찍을 때는 새 이름만 쓴다
- 기존 4종으로 학습한 가중치(best.pt)는 6종 데이터로 다시 학습해야 6종을 구분한다
- 같은 YOLO 모델을 본센터 탑뷰 카메라(공용 보관함 안 지갑 여러 개) 사진에도 쓴다. 탑뷰 사진도 세션을 나눠 찍어 학습 데이터에 넣는다.
- 세션(`s1`, `s2` …)은 촬영한 날이나 시간대가 다르면 새 번호를 쓴다. 학습/검증은 세션 단위로 나눈다.

## 하루 흐름
```
[교육원] capture_images.py 로 촬영 → Label Studio 라벨링 → prepare_dataset.py
        → python tools/hub_sync.py upload --kind data --local datasets/vision_v1103 --path vision_v1103
[집 PC]  python vision/train_yolo.py --dataset vision_v1103 --name yolo26l_v1106 --download --upload
        → 디스코드에 "학습 완료 · mAP" 알림
[교육원] python tools/hub_sync.py download --kind model --path yolo26l_v1106 --local models/yolo26l_v1106
        → 평가 → 기존보다 좋으면 models/stable/ 로 확정
```

## 촬영 예시
```
python vision/capture_images.py --category card_wallet --object W01 --session s1
```
- 스페이스: 한 장 저장 · a: 자동 연속 저장 켜기/끄기(기본 15프레임 간격) · q: 끝내기
- 화면에 `BLUR`가 빨갛게 뜨면 초점이 흐린 상태. `--skip-blurry`를 붙이면 흐린 사진은 저장하지 않는다.
- 카메라가 안 열리면 `--source 1` 또는 `--source 2`로 번호를 바꾼다.

## 시험
```
python -m unittest discover -s tests -v
```
웹캠·GPU 없이 돌아간다. 실제 학습(ultralytics)은 가짜 모듈로 흐름만 시험한다.

## 탑뷰 단일 이미지 추론과 ArUco 좌표 보정 (LF-3)

YOLO 검출·crop·중심 좌표·ArUco 보정은 [TOPVIEW.md](TOPVIEW.md)를 참고하세요. 촬영·학습 설정과 6종 데이터셋 예시(`configs/data_six_class.example.yaml`)는 같은 6종 이름·순서를 씁니다(11/6).

## 현재 검출 현황

USB·립밤 미검출, 신뢰도 비교 결과와 후속 학습 계획은 [DETECTION_STATUS.md](DETECTION_STATUS.md)를 참고하세요. 소수 로컬 테스트 사진에 대한 관찰이며 전체 물품 성능 평가 결과는 아닙니다.
