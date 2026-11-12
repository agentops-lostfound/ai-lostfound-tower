# 게시 전 검증 — 2026-11-12

대상은 제공 ZIP의 v0.2.80과 게시용 환경변수·문서 정리본이다. 클라우드 Linux / Python 3.12에서 확인했으며 원본 Windows / GPU / 로봇 결과와 구분한다.

## 통과

- Python 소스 99개 AST 구문 검사.
- `node --check beta/static/beta.js`.
- 다음 4개 모듈 **24개 시험 통과**:

```bash
python -m unittest beta.test_snug_fit beta.test_categories beta.test_registry_edit beta.test_nearest_edge
```

- 장비 환경변수 미설정 시 HTTP/장비 조회 전에 설명을 반환하는 것을 requests mock으로 확인.
- 사진·가중치·DB·캐시·원본 장치 ID·개인 Windows 절대 경로·정적 보정/집기 JSON 제외 확인.
- `git diff --check`.

## 팀 루트 시험

팀 규칙에 따라 저장소 루트에서 `python -m unittest discover -s tests`를 실행했다. 초기 실행은 langsmith/langgraph 등 클라우드 패키지 누락으로 실패해 의존성을 보완했다.

의존성 보완 후 전체 **1,957개: 성공 1,887 / 건너뜀 60 / 오류 10 / assertion 실패 0**이었다. 오류 10개는 기존 `test_taught_return`의 localhost HTTP 시험에서 403이 발생한 것이다. 이 모듈은 테스트 중 환경변수를 비워 `NO_PROXY`가 사라지므로 클라우드 프록시를 통해 루프백 서버에 요청했다.

제품·시험 파일을 고치지 않고 별도 시험 프로세스에서 `urllib.request.proxy_bypass`가 localhost/127.0.0.1에 대해서만 True를 반환하게 한 뒤 같은 모듈 전체를 재실행했다. **14개 모두 통과**했다. 다른 주소의 프록시는 유지했다. 전체 1,957개를 이 우회 조건으로 다시 실행한 것은 아니므로 최초 전체 명령을 무조건 통과했다고 기록하지 않는다. GitHub Actions 결과는 PR에서 별도로 확인한다.

## 실행하지 않은 것

실제 GPU 추론·모델 학습·카메라·시리얼 연결·토크 전환·로봇 이동은 실행하지 않았다. 새 폴더의 전체 테스트도 통과했다고 주장하지 않는다. 원본 인계에 남아 있는 `beta.test_robot_actions`, `beta.test_grasp_flow`의 기존 테스트 문제와 실물 의존성이 있어 별도 장비 환경에서 확인해야 한다.

## 실물 확인 범위

원본의 통합 진행 기록은 v0.2.80 변경 직전 폰 파지를 `held_likely`로 보고하고 놓기 이송 중 STOP했다고 기록한다. v0.2.80의 변경 자체 및 집기→놓기→HOME 전체 완료는 이 게시본에서 검증하지 않았다. 실제 장비 배포 전 제공자가 진행 중인 디버깅의 최종 결과와 비교한다.
