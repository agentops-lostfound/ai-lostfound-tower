# 팀 프로그램 연동 안내

이 브랜치는 독립 콘솔을 추가한다. 기존 `agents/`·`vision/`·`robot/`의 실행 코드를 교체하지 않는다. 다른 업무 브랜치에서는 `git fetch origin` 후 `git merge origin/pil2ya_02`로 파일을 가져올 수 있다. 병합 전에 자신의 변경을 보존하고 차이를 확인한다.

Field Vision 작업 디렉터리에서 실행하고 localhost API를 호출한다. 원격 서비스 인증·팀 DB 동기화·작업 큐 어댑터는 아직 없다. 다른 PC와의 연결을 위해 서버 바인딩만 바꾸는 것은 이 게시 범위에 포함되지 않는다.

## 읽기와 분석

| 요청 | 용도 |
|---|---|
| `GET /api/health` | 버전·워커·관절 방향 확인 |
| `GET /api/state` | 모델·카메라·분석 작업 상태 |
| `GET /api/events` | SSE 이벤트 |
| `GET /api/registry` | 이 베타의 등록 물품 목록 |
| `GET /api/observations` | 저장한 관측 결과 |
| `GET /api/prototype/state` | 집기·로봇 시퀀스 상태 |
| `GET /api/manual/state` | 로봇 연결·관절 피드백 |
| `POST /api/analyze` | `camera`, `kind`, `with_features` 또는 `data_url`로 분석 요청 |
| `POST /api/search` | `text`, 선택적 `data_url`, 선택적 `category`로 검색 |
| `POST /api/cancel` | 비전 분석·감시 취소 |

예: `POST /api/search`에 `{"text":"하늘색 핸드폰","category":"phone"}`. 먼저 이 베타 DB에 참조 물품이 등록돼 있어야 한다. `engine.submit()`이 돌려주는 작업 식별자를 보관하고 작업 상태를 확인한다. 요청 응답이 곧 분석 완료나 실제 물품 일치라는 뜻은 아니다.

## 실제 로봇 동작

`POST /api/manual/connect`는 Studio 등록정보를 읽어 별도 시리얼 워커를 연결한다. Studio runtime 세션을 닫고 포트를 단일 소유해야 한다. 연결 설정은 README의 환경변수를 따른다.

검색이 완료된 작업 ID를 `POST /api/prototype/start`의 `search_job_id`로 전달한다. 선택적 `approach_height_mm`, `grasp_height_mm`, `measure_only`를 받는다. `measure_only=true`는 접근·개방·보정 후 하강 전에 멈추는 실장비 측정 모드이며 무동작 시뮬레이션이 아니다. HTTP 요청 완료와 전체 로봇 시퀀스 완료를 구분한다.

`POST /api/prototype/stop`은 로봇 시퀀스 중단, `POST /api/prototype/home/go`는 HOME 동작, `POST /api/prototype/gripper/open`은 집게 개방이다. 비전 취소 API를 로봇 정지로 취급하지 않는다. 실제 필드·응답 구조는 `beta/server.py`, `beta/grasp_flow.py`, `beta/robot_actions.py`를 기준으로 확인한다.

## 어댑터 작성 시 결정할 것

- 팀 접수 ID와 베타 SQLite의 등록 ID를 어떻게 연결할지 정한다. 팀 ID를 베타 ID로 자동 간주하지 않는다.
- 검색 실패·대상 경쟁·미확정 파지·실패·STOP·놓기 완료를 별도로 전달한다. `held_likely`는 자동 판정이며 확정된 실물 성공과 구분한다.
- 팀 운영 품목과 이 실험의 6품목을 합칠지 결정한다. 기존 `agents/contracts.py`는 이 브랜치에서 바꾸지 않았다.
- 모델은 워커 한 곳에서 관리하고 다른 프로세스에서 중복 로드하지 않는다.
- 가중치·메타·장비 보정·카메라 설정을 별도로 준비한다. 제외된 원본 `beta_data/` 전체를 다른 장비에 그대로 적용하지 않는다.

필요한 기능만 가져오는 경우에도 상대 import와 데이터 루트는 유지한다. `beta/config.py`의 `ROOT`는 `beta/`의 상위 폴더이고 `DATA`는 그 아래 `beta_data/`다.
