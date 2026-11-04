# LF-11·12 검토: 비전 검출에서 로봇 이동까지의 연결 상태

2026-11-04 · 원격 브랜치 코드 읽기 검토. 장비 구동·모델 실행·브랜치 병합 없음.

검토 기준: main `61a0133`, LF-3-yolo-aruco `5160004`, LF-2-haeundae-found-item-form `b8b7e01`. 코드 존재와 현장 성능을 구분한다.

## 현재 구현 흐름

1. 비전 run_image는 이미지 파일을 읽고 같은 프레임에서 ArUco와 YOLO를 실행한다. 기본 configs/vision.yaml은 COCO YOLO26n, imgsz=640, confidence=0.25다. Jira의 YOLO26s 표현과 실제 기본값이 다르다.
2. YOLO는 bbox·class·confidence와 중심 픽셀 `[(x1+x2)/2,(y1+y2)/2]`을 반환하고 원본 이미지에서 crop을 저장한다. 중심은 실제 파지점·물체 높이·방향이 아니다.
3. ArUco는 검출한 마커 코너 픽셀과 사용자가 실측한 작업대 mm 대응점으로 homography를 만든다. bbox 중심을 변환해 center_world_mm을 만들며 유효 보정이 없으면 null이다. 현재 기본·item 설정의 markers_mm은 비어 있다.
4. crop을 Qwen3-VL-2B-Instruct로 순차 입력해 general_items_v1 특징을 만든다. YOLO 클래스명을 프롬프트에 주입하지 않는다. JSON 형식 검증과 실제 시각 정답은 별도다.
5. main의 SequenceFileVisionPart는 미리 생성한 result_with_qwen.json을 읽어 계약 형식 box·center·features로 변환한다. center는 픽셀이고 선택적으로 center_mm도 남긴다. 기본 파일 나이 제한은 600초이며 파일 나이가 짧아도 장면이 그대로라는 보장은 없다.
6. main의 PolicyMatcherPart는 DB 특징과 검출 특징의 품목·색·스티커 및 자유 특징 점수를 정책으로 비교해 검출 index를 고른다. 관제탑 어댑터의 자유 특징 비교 기본은 낱말 겹침이며 모든 경로가 임베딩 기반인 것은 아니다.
7. supervisor.approach는 선택된 검출의 **center(픽셀)**를 robot_approach에 전달한다. center_mm을 사용하는 구현은 이 호출 경로에 없다.

## 실제 SO-ARM 제어 연결 여부

조회한 main·LF-3·LF-2 브랜치에서 로봇 함수는 Protocol 선언과 MockBackend 구현을 확인했다. MockBackend는 성공/실패 플래그와 호출 이력을 반환하며 모터에 명령하지 않는다. robot 폴더에는 README만 있다. CompositeBackend는 실제 로봇 부품을 주입할 구조지만 기본은 MockBackend fallback이다.

문서상 예정 흐름은 픽셀→로봇 좌표 변환→Home/경유점/접근 자세, SmolVLA 근거리 집기·확인, 저장된 경로의 바구니 전달이다. 실제 작업대→로봇 기준 변환, z/접근 높이·방향, 역기구학/관절 명령, SmolVLA 정책 실행·대상 조건 지정, 물리 로봇 API/시리얼 연결은 이 브랜치들에서 구현을 확인하지 못했다. 사용자 PC에 별도 구현이 존재하지 않는다고 단정하는 것은 아니다.

특히 ArUco의 작업대 평면 x/y mm만으로 로봇은 움직일 수 없다. 실제 로봇 기준 좌표와 장착 위치, 높이·자세·도달 범위, 파지점과 충돌·실패 처리 정의가 필요하다. 기존 SO101 관절 캘리브레이션 완료 보고는 카메라↔로봇 좌표 보정 완료를 뜻하지 않는다.

## 검출·모델 최신 상태 보완

DETECTION_STATUS.md는 소수 로컬 사진에서 USB·립밤 미검출과 Qwen 문자·스티커 오판을 보고한다. confidence를 낮춰 배경 오검출이 늘어난 사례가 있으며 전체 품목 정량 성능 확보로 해석하지 않는다. item 단일 클래스 학습 설정·스크립트는 있으나 실제 학습 완료·가중치 검증 보고는 아니다.

이전 Qwen 지연 분석 때 없던 qwen 소스가 LF-3 브랜치에 추가됐다. settings 기본 max_new_tokens=512, retries=1(환경값 변경 가능), worker max_edge=512 덮어쓰기다. load_model은 lru_cache(maxsize=1)로 동일 Settings 재사용 시 프로세스 내 캐싱하며 GPU 전체 배치·NF4를 검사한다. 요청별 프로세스 재생성 비용은 여전히 남는다. 과거 분석의 외부 로더 미확인 상태는 이 소스 검토로 보완되지만 사용자 PC 실제 설정·성능은 재측정하지 않았다.

## 역할 및 다음 협의

사용자 제공 최신 Jira 기준 pil2ya/이순필은 LF-11 작업대·시연 녹화·반환 경로, LF-12 반환 안전, LF-18 통합 시연·발표 담당이다. 김건태는 LF-3 검출·LF-20 매칭·LF-19 정책 학습·LF-21 좌표 보정/사전 접근, 변재원은 LF-8 DB와 관제탑 LF-14~17 담당이다. Jira 상태를 직접 갱신하거나 업무 완료를 선언하지 않았다.

- LF-21: 픽셀/작업대 mm/로봇 좌표의 소유 책임과 실측 변환·접근 높이·검증 규칙 합의.
- LF-19: 선택 개체를 SmolVLA에 지정하는 입력과 집기 성공 판정·재시도 조건 합의.
- LF-11: 고정된 작업대·안전 경유점·담당자 전달 경로를 준비하고 실제 로봇 부품 연결 시험.
- LF-12: 오래되거나 바뀐 장면·무효 보정 시 이동 금지, 정지와 자동 Home 복귀의 분리 검토. 현재 문서의 '정지 후 Home'은 상황에 따라 추가 이동 위험이 있어 실행 정책 확인 필요.
- 현재 supervisor는 바구니 전달 후 인계 완료를 기록한다. 사용자 요구의 담당자 최종 인계 사건과 구분하는 설계 검토가 필요하며 이번 작업에서는 공통 계약·팀 코드를 수정하지 않는다.
