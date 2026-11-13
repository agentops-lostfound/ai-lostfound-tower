# 탑뷰 보관함 검증 (로컬, 읽기 전용)

`top-view-locator-20261111.zip`의 OWLv2 + SigLIP2 관측을 R1-1~R4-2에 배정하고,
관제탑 `GET /api/admin/storage`의 운영 상태와 개수·품목을 비교한다.
DB 변경, 검사 결과 POST, 로봇 제어는 호출하지 않는다.

## 이 PC에서 실행

다른 PC는 `config.example.json`을 `outputs/topview_bridge/config.json`에 복사하고
Studio 프로젝트·환경·탑뷰 카메라 ID를 해당 PC 값으로 채운다. 예제의 균등 8칸은
실물 보정값이 아니다. 카메라 연결 후 **칸 영역 수정**에서 실제 칸을 그려 저장해야 한다.
기준 마커가 없는 예제 설정은 비교를 확정하지 않는다.
원본 ZIP은 별도로 확보해 `outputs/topview_bridge_research/locator-20261111/`에 풀고,
두 모델을 준비한 뒤 아래 `prepare` 명령으로 복사한다. ZIP·참조 사진·가중치는 Git에 포함하지 않는다.

저장소 루트 `C:\Users\user\AI-LostFound\team-repo`에서:

```powershell
.\.venv\Scripts\python.exe -m vision.topview_bridge.server --config outputs/topview_bridge/config.json
```

화면: <http://127.0.0.1:8770>. **지금 분석**은 현재 프레임 한 장을 검사한다.
**자동 감시**는 이전 분석 종료 후 15초가 지나면 다음 프레임을 검사한다.
영상은 약 3fps로 표시하며, 모델 분석은 프레임마다 실행하지 않는다.
분석 중에는 이전 완료 프레임/결과를 유지한다.
API 8100이 응답하지 않아 실제 응답을 확인한 관제탑 앞문 8080을 현재 설정에 사용한다. 결과에는 촬영 시각이 표시된다.
**분석 프레임 보기**로 박스와 분석한 원본을 함께 확인할 수 있다.

- Python: `.venv`의 OpenCV, numpy, websockets (CUDA torch 설치 불필요).
- 카메라: Studio `127.0.0.1:7860`의 이미 실행 중인 `topview` 공유 세션.
  USB를 직접 열거나 Studio·로봇 세션을 재시작하지 않는다.
- DB: `http://10.10.21.21:8080/api/admin/storage`. 모의 운영에서는 메모리가 원본이고
  PostgreSQL은 미러일 수 있다. 화면은 조회한 API 주소를 상태 JSON에 남긴다.
- 인증이 필요하면 실행 프로세스에 `TOPVIEW_TOWER_TOKEN`을 설정한다. `.env`를 읽지 않는다.
- 추론: WSL `Ubuntu-24.04`, 실행 중인 Docker `physical-ai-studio-cuda`의 기존 CUDA Python.
  Studio의 패키지/코드는 변경하지 않으며 별도 작업 프로세스가 모델을 순차 로딩한다.

로컬 설정, 실물 사진, 결과, 모델은 무시되는 `outputs/topview_bridge/`에만 저장한다.
현재 ZIP 복사본은 `outputs/topview_bridge_research/locator-20261111/`다.
Docker 내부 자료는 `/tmp/lf-topview-bridge/locator`와 `/tmp/lf-topview-bridge/models/`다.
컨테이너를 재생성하면 로컬 캐시에서 다시 복사한다:

```powershell
.\.venv\Scripts\python.exe -m vision.topview_bridge.prepare --config outputs/topview_bridge/config.json --locator-root outputs/topview_bridge_research/locator-20261111 --models outputs/topview_bridge/models
```

`prepare`는 준비된 소스/설정/가중치만 복사한다. 최초 모델 다운로드는 별도 설치 단계다.
모델 ID: `google/owlv2-base-patch16-ensemble`, `google/siglip2-base-patch16-224`.
Qwen은 사용하지 않는다. 추론 중에는 기존 `agents.gpu_lease`의 `test` 사용권을 잡고,
자식 프로세스가 끝난 뒤 돌려준다. 모델과 GPU 메모리는 매번 해제한다.
시간 제한은 Docker 안에서 적용되어 Windows 래퍼만 종료하고 GPU 작업을 남기지 않는다.

## 영역과 판정

칸은 왼쪽부터 R1 휴대폰, R2 보조배터리, R3 핸드크림, R4 립밤이다.
각 열의 위/먼 쪽은 -1, 아래/가까운 쪽은 -2다.
초기 픽셀 영역은 2026-11-11 실제 1280×720 영상의 받침대 위치를 보고 정했다.
**칸 영역 수정**에서 8개 직사각형을 바꿀 수 있다. 영역 중복/화면 밖 저장은 거부한다.
편집 시작 시 고정 사진을 만들고, 해당 사진의 해상도·카메라 ID·보이는 ArUco 모서리를 함께 기록한다.
저장할 때 판/카메라가 움직였거나 편집 사진이 5분 경과했으면 저장을 거부한다.
해상도 변경, 기준 마커 미검출, 모서리 이동 12px 초과이면 분석을 보류한다.
현재 고정 영상에서는 마커 0·1이 보이므로 4마커 mm 보정 대신 픽셀 영역을 사용한다.
보이는 마커 주변 기준이므로 보관판 전체의 변형이나 모든 원근 변화를 보증하지 않는다.
카메라/보관판을 옮기면 영역을 다시 지정해야 한다.

| 상태 | 의미 |
|---|---|
| count_match | 개수와 품목 일치 또는 빈 칸 일치 |
| missing_candidate | DB 1개, 유효 검출 0개 — 미검출/빈 칸 후보 |
| unexpected_candidate | DB 빈 칸, 유효 물품 검출 |
| category_mismatch | 점유 수는 같지만 검출 품목이 다름 |
| multiple | 한 칸에 여러 검출, 중복 검출/다중 적재 검토 |
| ambiguous | review 검출, 박스 겹침, 경계 근접 |
| transition | 반환 등 전환 상태, 미확인 상태 또는 로봇 동작 중 |
| unavailable | 카메라·DB 실패, 분석 중 배정/영역 변경, 결과 만료 등 |

현재 운영 4종의 accepted만 수량에 포함하고 review는 해당 칸의 일치 확정을 보류한다.
ZIP에 남은 지갑·USB는 운영 품목 외 검토 후보로 보존한다.
중심의 칸, 박스 포함률 55%, 다른 칸 겹침 30%, 경계 10px를 함께 확인한다.
지원 품목의 검출기이며 임의의 물건이나 가림을 모두 검출하는 것은 아니다.
미검출은 분실 확정이 아니다. 같은 칸 상태가 3회 연속이면 지속 후보로 표시한다.
분석 전후 운영 배정을 비교하고, 주기 조회에서도 변경/동작을 감시한다.
폴링 사이에 발생했다 끝난 변동까지 검증하는 트랜잭션 보장은 없다.
연결 실패나 결과 촬영 후 90초 경과 시 이전 결과를 현재 일치로 표시하지 않는다.

ZIP의 `Red_lip`, `TEST_U01` 참조 ID는 관제탑 `A-/S-` ID와 연결되지 않았다.
따라서 **개체 ID 일치 여부는 항상 미확인**이다. 같은 품목 두 개의 자리 교환은
현재 수량·품목 비교만으로 검출할 수 없다.

결과: `outputs/topview_bridge/latest.json`, 분석 원본: `analysis.jpg`,
추론 오류: `detector.stderr.log`. HTTP JSON은 `/api/state`로 읽을 수 있다.
서버는 loopback에만 바인딩하고 변경 요청은 같은 출처만 허용한다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_topview_bridge -v
.\.venv\Scripts\python.exe -m unittest discover -s tests
```
