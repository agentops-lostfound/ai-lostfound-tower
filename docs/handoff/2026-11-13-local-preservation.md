# 2026-11-13 로컬 파일 분류 및 복구 인수인계

## GitHub 보존 범위

Git 밖의 비전 소스 49개를 `archive/geontae-local-20261113/`에 보존했다.
관제탑의 운영 모듈을 이 보존본으로 교체하지 않는다. 원본 검증 기록과 현재 운영 적용 여부는 구분한다.

로컬 통신 안정화 변경은 `LF-21-geontae-remote-link-stability` 브랜치에 별도로 보존한다.
게시 커밋은 `f07b5ca`이며, UTF-8 환경의 전체 unittest 1,592개 중 23개 조건부 제외, 실패·오류 0개를 확인했다.
그 브랜치는 과거 기준 `2d88070`에서 이어진 수정으로, 최신 main에 직접 덮어쓰는 배포 지침이 아니다.
일반 응답 대기 5초와 독립 heartbeat, 해당 모의 HTTP 시험, 재개 설계·적용 안내가 포함된다.
자동 재개는 설계이며 구현 완료로 간주하지 않는다. 운영 반영에는 최신 main과의 별도 통합 검토가 필요하다.

## 로컬 보존 묶음

프로젝트 루트의 `preservation-20261113/`에 구성했다. 해당 폴더와 대용량 자료는 GitHub에 올리지 않는다.

| 분류 | 내용 | 용량(십진 GB, 반올림) |
|---|---|---:|
| `drive-ready` | 코드 스냅샷·미커밋 overlay·로봇 자세와 보정·Studio DB/캘리브레이션·비전 관측·문서·영상·자체 모델 | 1.81 |
| `usb-extra` | 전체 Git bundle·Studio Docker 이미지·공개 모델 | 20.48 |
| `github-review` | 게시 후보와 후속 처리 목록 | 소량 |

이는 로컬 구성 완료 상태이며 Google Drive 업로드나 USB 복사 완료를 의미하지 않는다.
USB에는 `usb-extra`와 `drive-ready`를 함께 복사한다. 공개 모델은 재다운로드할 수 있으므로 Drive 필수 묶음에서는 제외했다.

## 코드와 현장 실행 버전

보존 당시 원격 main은 `dc09427`, 개발 작업트리 `team-repo`는 `ef95c6d`,
로봇 원격 실행 작업트리 `remote-home-worktree`는 `39f069d`였다.
각 작업트리 HEAD·브랜치·변경 목록은 `drive-ready/01-code/worktrees.json`에 기록했다.
이 기록은 스냅샷 시점의 값으로, 이후 GitHub 커밋이나 최신 main을 뜻하지 않는다.

- HEAD ZIP을 풀고 동일 작업트리의 `local-overlay.zip`이 있으면 적용한다.
- `working.patch`는 overlay와 같은 변경의 검토용이다. 둘을 중복 적용하지 않는다.
- Git 이력이 필요하면 `usb-extra/01-git-history/ai-lostfound-tower.bundle`을 clone한 뒤 필요한 브랜치로 전환한다.
- Git 밖의 비전 소스는 이번 보존 디렉터리 또는 `local-vision-source.zip`으로 복원한다.

## 장비·환경 복구

1. 코드의 requirements/lock 파일과 `00-guide/environment` 패키지 목록을 참고해 새 가상환경을 만든다. 기존 `.venv`는 복사하지 않는다.
2. 필요 시 USB용 Studio 이미지를 `docker load`한다. `02-robot`의 현재 application/data/calibration TAR가 기존 환경 참고본보다 우선한다.
3. Studio DB는 SQLite 온라인 백업으로 저장했다. 현재 자세 파일의 `poses`, `motion_profiles`, `command_corrections`도 포함했다.
4. 카메라·USB 장치 이름과 포트는 새 PC에서 확인한다. 다른 PC에서의 재설치·실물 동작 검증은 아직 수행하지 않았다.
5. 공개 모델 ZIP은 내부 상대 경로대로 프로젝트 루트에 풀고, 필요하면 새 PC의 캐시 경로 설정을 조정한다.

## 제외 및 남은 항목

- `.env`, 인증 토큰, 개인키, Windows DPAPI `auth.clixml`은 읽거나 복사하지 않았다. 새 PC에서 다시 설정한다.
- 재원 PC의 운영 PostgreSQL 데이터는 이 PC의 백업에 포함되지 않는다. 운영 DB 보존은 별도 덤프가 필요하다.
- 삭제한 SmolVLA 가중치, 기존 백업 전체, 재설치 가능한 가상환경·패키지 캐시, 반복 실행 로그는 제외했다.
- 접근 제한된 과거 임시 폴더 `robot_db_check/push-checkout-_dfv1o0r`는 11/12 백업본으로 보완했다. 현재 원본의 이후 변경 여부는 확인하지 못했다.
- 원본 폴더와 기존 백업은 유지했다. 새 PC 복구 확인 전 삭제하지 않는다.

보존 묶음의 ZIP 22개 CRC, Git bundle 및 Studio SQLite 검사를 통과했다.
묶음의 `manifest.json`, `manifest.sha256`, `verification.json`에 무결성 정보와 확인 범위를 기록했다.
