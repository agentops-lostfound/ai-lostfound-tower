# Field Vision — 팀 인계와 실행 코드

**2026-11-13 현황:** 로컬 개발본은 **v1.0.10 / 20261113.11**이며, 이 저장소의 실행 코드는 PR #266으로 공유한 **v0.2.80**이다. 이번 변경은 최신 로컬 대조 인계를 문서로 반영한다. v1 코드·캡처·영상은 아직 이 게시본에 포함되지 않았다.

팀원은 다음 순서로 확인한다.

1. [최신 구현·실물 확인·남은 일](docs/handoff/2026-11-13-current-status.md)
2. [발표 설명·모델 역할·수치·필요 자료](docs/presentation/2026-11-13-field-vision.md)
3. [다음 코드 제출의 포함·제외·차이](docs/progress/2026-11-13-publication-plan.md)
4. [기존 팀 프로그램 연동](INTEGRATION.md)

아래 실행 절차와 기본값은 **저장소에 있는 v0.2.80 코드**의 안내다. 최신 로컬 운영 설정과 구분한다. 브랜치를 병합하는 것만으로 v1 실행 코드나 관제탑 어댑터가 설치되지는 않는다.

## 게시된 v0.2.80 실행본

탑뷰에서 등록 물품의 현재 위치·방향을 찾아 SO-101이 접근하고, 손목 카메라로 정렬·간격을 보정해 집은 뒤 지정 위치에 놓는 독립 실행 베타다. 기존 팀 프로그램과 연결하기 위한 검토용 스냅샷이다. 원본은 계속 디버깅 중이며 이 브랜치의 실행 결과와 원본 PC의 결과를 구분한다.

- 코드 기준: 업로드된 `Start-Beta.zip`, `beta/version.py` = 0.2.80 / 20261112.80.
- 통합 화면: 검색·집기 / 실시간 관측 / 등록 물품 / 수동 제어 / 설정 / 기록·진단.
- 접근 목표는 현재 검출 좌표로 계산한다. 물품별 고정 칸·접근 자세를 선택하는 방식은 아니다.
- 큰 물품 처리는 품목명 대신 탑뷰에서 측정한 폭 60mm 이상을 기준으로 한다.
- 팀 운영 품목과 별개로 이 베타는 phone / wallet / hand_cream / usb / lip_balm / power_bank 6품목을 다룬다. 팀 계약과 운영 품목 설정은 변경하지 않았다.

## 실행 준비

원본 환경은 Windows, Python 3.11, RTX 3050 6GB, RAM 16GB다. 아래는 새 환경의 설치 절차이며 클라우드에서 GPU·실장비 재현까지 검증한 것은 아니다.

저장소 루트에서 PowerShell:

```powershell
Set-Location robot/field_vision
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r beta/requirements.txt
.\.venv\Scripts\python.exe -m pip install opencv-python==5.0.0.93
.\.venv\Scripts\python.exe -m beta.prepare_models
.\Start-Beta.cmd
```

브라우저 주소는 `http://127.0.0.1:8871/`다. 모델 다운로드는 네트워크·디스크 공간이 필요하다. 원본의 `requirements-lock.txt`는 초기 환경 기록이고 최종 베타 전체 의존성을 잠근 파일은 아니다. `beta/requirements.txt`도 함께 설치한다.

학습 YOLO 가중치는 포함하지 않았다. 제공자가 별도로 전달한 `best.pt`와 해당 가중치의 `meta.json`을 `models/detector/`에 둔다. `trained_classes`가 활성 품목을 모두 포함할 때 탑뷰 YOLO 단독 판정을 사용한다. 파일이 없으면 원본 PC의 6품목 단독 모드가 재현되지 않고 OWLv2 경로를 사용한다. Hugging Face 모델 캐시 준비와 YOLO 가중치 준비는 별개다.

카메라 번호·장치 경로·요청/실제 해상도는 설정 화면에서 맞춘다. 초기 기본값은 장비별로 다르므로 원본 PC와 같다고 가정하지 않는다.

## 로봇 연결

현재 로봇 제어는 `physical-ai-studio-cuda` 컨테이너 안의 별도 `manual_worker.py`를 실행한다. 컨테이너에 `scservo_sdk`와 시리얼 장치 접근이 준비돼 있어야 한다. 팀 관제탑의 로봇 어댑터와는 아직 연결하지 않았다.

서버 실행 전에 자신의 Studio 등록정보로 환경변수를 설정한다.

```powershell
$env:FIELD_VISION_FOLLOWER_SERIAL = "본인 팔로워의 일련번호"
$env:FIELD_VISION_PROJECT_ID = "Studio 프로젝트 UUID"
# 다른 주소·컨테이너를 쓰는 경우에만:
$env:FIELD_VISION_STUDIO_API = "http://127.0.0.1:7860/api"
$env:FIELD_VISION_STUDIO_CONTAINER = "physical-ai-studio-cuda"
.\Start-Beta.cmd
```

원본 장치 일련번호·프로젝트 ID는 게시본에서 제거했다. 설정이 없으면 로봇 연결 요청에 설명을 반환한다. Studio 런타임이 포트를 사용 중이면 직접 연결을 거부한다. 다른 제어 프로그램과 동시에 포트를 사용하지 않는다.

실행 데이터는 이 폴더의 `beta_data/`에 생성한다. DB·등록 사진·학습값·ArUco 정합·손가락·HOME·놓기 자세·장비 보정값은 포함하지 않았으므로 자신의 장비에서 설정해야 한다. 원본 PC의 저장된 놓기 자세와 workflow 설정은 새 설치에 자동으로 생기지 않는다. 새 설치 기본 종료 방식은 `hold`, 추가 닫기는 1.5초, 보정 한도는 12mm다. 원본 운영값(return / 2초 / 20mm)과 다르다.

STOP은 소프트웨어 중단이다. 장비 연결·수동 토크·집기·HOME·놓기 버튼은 실제 로봇을 제어한다. 데모 사진과 예전 보정·집기 결과 JSON은 제외했으며 관련 이전 화면의 샘플/기록은 사용자가 준비한 자료가 있어야 보인다.

## 기존 프로그램에 연결하기

이 폴더를 독립 작업 디렉터리로 실행한다. 기존 루트 `tests/`, 팀 서버·DB·계약 파일은 변경하지 않았다. 충돌 없이 병합해도 API 어댑터·접수 ID 연결·인증·배포는 별도 구현이 필요하다.

연결 지점과 입력 형식은 [연동 안내](INTEGRATION.md)를 참고한다. 현재 서버는 localhost 전용이다. 외부 접속을 위해 host 제한만 풀어 공개하지 않는다.

## 상태·검증

[게시 인계](TEAM_HANDOFF_20261112.md)와 [검증 결과](VALIDATION.md)를 먼저 읽는다. `docs/progress/`는 시간순 개발 기록이므로 과거 실패·설정·미완료 설명을 현재 상태로 적용하지 않는다. [초기 사용 기록](BETA_README.md)은 0.1 시점 설명을 포함한다.

원본 제공 기록에는 USB 파지와 핸드폰 첫 파지가 있다. v0.2.80의 밀착 거리 개선 자체와 집기→놓기→HOME 전체 성공은 이 게시본에서 실물 검증하지 않았다. 병합·실장비 배포는 사용자가 판단한다.
