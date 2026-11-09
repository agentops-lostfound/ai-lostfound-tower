# Physical AI Studio 공유 파일과 설치 순서

## 팀원용 빠른 순서

**흐름: main 받기 → Studio·장비 준비 → 압축 확인·해제 → 점검 → 설치 → 화면 확인.**

이 안내는 Windows PowerShell + WSL `Ubuntu-24.04` + 실행 중인 Studio 컨테이너 `physical-ai-studio-cuda` 기준이다.
지원 대상은 아래 [다른 PC에서 준비하기](#다른-pc에서-준비하기)에 적힌 Studio revision과 기존 v4 backend, 같은 Follower 등록 ID·장비 조건이다.
새 PC에서 Studio 자체 설치와 장비 등록을 먼저 완료해야 한다. 다른 로봇·다른 보정·다른 Studio 버전은 환경에 맞춘 묶음을 따로 준비한다.

### 1. 최신 파일 받기

이 공유 PR이 `main`에 병합된 뒤, 저장소 폴더의 PowerShell에서 실행한다.
작업 중인 변경은 먼저 본인 브랜치에 보관한다. Git 명령이 실패하면 다음 단계로 넘어가지 않는다.

```powershell
git switch main
if ($LASTEXITCODE -ne 0) { throw 'main 전환 실패: 현재 작업 상태를 확인하세요.' }
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'pull 실패: Git 상태를 확인하세요.' }
```

### 2. Studio와 장비 준비하기

Docker/WSL과 기존 Studio를 켜고 [http://localhost:7860](http://localhost:7860)에 접속되는지 확인한다.
Studio에서 로봇 runtime 연결과 녹화를 종료한다. Studio 서버·컨테이너는 켜 둔다.
로봇·리더·카메라의 USB가 WSL에 연결돼 있어야 컨테이너를 정상 재시작할 수 있다.
다른 프로그램이 같은 팔이나 카메라를 사용하고 있으면 먼저 정상 종료한다.

아래 확인 명령은 장치에 이동 명령을 보내지 않는다.

```powershell
wsl -l -v
wsl -d Ubuntu-24.04 -- docker ps --filter name=physical-ai-studio-cuda
```

목록에 해당 WSL 배포판과 실행 중인 Studio 컨테이너가 없다면 설치 환경부터 준비한다.
컨테이너가 중지돼 있다면 장치 연결·노드 경로를 먼저 확인하고 기존 Studio 설치 절차로 기동한다.

### 3. 설치 압축본 풀기

아래 블록을 그대로 실행한다. 압축본의 검증 해시를 먼저 확인한 뒤 압축을 푼다.

```powershell
$studioArchive = 'outputs/studio_pose_integration/bundle.tar.xz'
$studioExpectedHash = ((Get-Content "$studioArchive.sha256" -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash -LiteralPath $studioArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $studioExpectedHash) {
  throw 'Studio archive SHA256 mismatch'
}
if (Test-Path 'outputs/studio_pose_integration/bundle') {
  throw 'bundle 폴더가 이미 있습니다. 기존 내용을 별도 보관한 뒤 진행하세요.'
}
tar -xJf $studioArchive -C outputs/studio_pose_integration
if ($LASTEXITCODE -ne 0) { throw 'Studio archive extraction failed' }
```

성공하면 `outputs/studio_pose_integration/bundle/bundle.json`과 `backend/`, `dist/`가 생긴다.
이미 `bundle/` 폴더가 있으면 자동 덮어쓰지 않는다. 기존 묶음과 새 묶음을 구분해서 보관한다.

### 4. 설치 전 점검하기

```powershell
wsl -d Ubuntu-24.04 --cd "$PWD" -- python3 robot/studio_extension/install.py --bundle outputs/studio_pose_integration/bundle
if ($LASTEXITCODE -ne 0) { throw 'Studio 점검 실패: 오류를 확인하세요.' }
```

출력에서 `bundle_verified: true`, `runtime_sessions: 0`, `missing_restart_devices: []`를 확인한다.
이 명령은 설치·재시작·로봇 이동을 하지 않는다. **점검 성공만으로 설치가 완료되지는 않는다.**
기존 backend가 묶음의 기준과 같은지 확인하는 원본 해시 검사는 다음 적용 단계에서 쓰기 전에 수행한다.

### 5. 튜닝본 설치하기

같은 장비·등록 ID·보정 조건이고 위 점검을 통과한 최초 설치 환경에서 실행한다.
**이 명령은 기존 파일을 백업하고 Studio 컨테이너를 재시작한다.**
이미 튜닝본이 있는 PC의 갱신에는 아래 [상황별 처리](#상황별-처리)를 따른다.

```powershell
wsl -d Ubuntu-24.04 --cd "$PWD" -- python3 robot/studio_extension/install.py --bundle outputs/studio_pose_integration/bundle --apply
if ($LASTEXITCODE -ne 0) { throw 'Studio 설치 실패: 오류를 확인하세요.' }
```

`Backup:` 뒤에 나오는 백업 경로를 기록한다.
`Studio is healthy. No robot connection or movement was requested.`가 나오면 서버 설치가 끝난 것이다.
이 단계는 로봇 연결이나 이동을 시작하지 않는다.

### 6. 화면과 사용 흐름 확인하기

브라우저에서 [http://localhost:7860](http://localhost:7860)을 열고 `Ctrl+F5`로 새로고침한다.
자기 프로젝트의 녹화 화면 또는 Model Run 화면에서 다음 항목을 확인한다. 일반 Environments 화면에는 새 버튼이 없다.

- 저장 자세 `pose_1`~`pose_8` 선택과 `선택 자세로 이동`
- `이동 시간` 3초·4초·5초 선택
- 리더·팔로워 관절값 비교 영역(연결 전에는 값이 대기 상태일 수 있음)
- 녹화 화면의 `집기 완료 · 저장 후 복귀`, Model Run 화면의 `집기 완료 · 어프로치 복귀`

화면 확인 뒤 실제 장비를 사용할 때의 순서는 다음과 같다.

1. 경로를 확인하고 어프로치 자세로 이동 → 실제 도착 확인.
2. 리더를 팔로워와 비슷한 자세로 직접 맞춤 → `리더 정렬 후 텔레 켜기`.
3. 녹화 시작 → 집고 안전한 높이로 들어 올림.
4. `집기 완료 · 저장 후 복귀` → 저장 확인 후 같은 어프로치로 복귀.

설치 성공과 실물 이동 검증은 별개다. 처음에는 빈 집게·작은 이동부터 확인한다.
자세 이동은 충돌 회피 기능이 없으며, 이동 중에는 `이동 정지 / HOLD`로 멈출 수 있다.
모델의 집기 완료 자동 판정과 리더 자동 정렬은 구현돼 있지 않다.

## 상황별 처리

| 상황·오류 | 다음 행동 |
|---|---|
| pull 후 압축본이 없음 | 공유 PR의 main 병합 여부, 현재 브랜치와 pull 성공 여부 확인 |
| `bundle 폴더가 이미 있습니다` | 기존 묶음을 별도 보관한 뒤 새 압축본을 해제. 기존 설치본의 백업도 보존 |
| `SHA256 mismatch` / `Bundle integrity check failed` | 설치 중단. Git 변경 여부 확인 후 정상 압축본을 다시 받아 새 폴더에 해제 |
| `Studio version changed` | 해당 Studio 버전에 맞춰 확장을 다시 빌드·검증해야 함 |
| `Installed source changed` | 순정·다른 수정본 또는 이미 튜닝된 설치. 현재 소스를 비교해 해당 환경용 묶음 준비 |
| `runtime_sessions`가 0보다 큼 | Studio에서 로봇 runtime 연결을 정상 종료하고 다시 점검 |
| `missing_restart_devices`에 경로가 표시됨 | USB의 WSL 연결과 컨테이너 장치 경로를 복구한 뒤 다시 점검 |
| 버튼이 보이지 않음 | Ctrl+F5 후 녹화/Model Run 화면 확인. 설치 로그와 접속한 Studio 서버 주소 확인 |
| 다른 팔·다른 보정·다른 Follower ID | 해당 장비를 등록·보정하고 자세 및 장비 ID를 반영해 전용 묶음 준비 |

설치 중 문제가 생겨 복구할 때는 실제 `Backup:` 경로를 사용한다. 장치를 연결하고 runtime 세션을 종료한 상태에서 실행한다.
아래 날짜 부분은 예시이므로 기록해 둔 실제 백업 경로로 바꾼다.

```powershell
wsl -d Ubuntu-24.04 --cd "$PWD" -- python3 robot/studio_extension/install.py --bundle outputs/studio_pose_integration/bundle --rollback outputs/studio_pose_integration/backup-YYYYMMDD-HHMMSS
```

---

## Git에서 받는 파일

`main`에 병합된 뒤 `git pull`하면 다음 파일을 함께 받는다.

| 경로 | 내용 |
|---|---|
| `robot/studio_extension/` | 확장 코드, UI 소스, 설치기, 테스트 |
| `outputs/studio_pose_integration/bundle.tar.xz` | 현재 PC에 적용한 backend와 배포 UI, 파일별 SHA256 목록을 담은 설치 묶음 |
| `outputs/studio_pose_integration/bundle.tar.xz.sha256` | 압축본 SHA256 |
| `outputs/robot_panel_live/poses.json` | 현재 장비에서 티칭한 12개 자세 |

압축본은 약 2.5MB다. 압축 전에는 약 20MB이며, 5MB가 넘는 UI 파일이 있어 압축해서 공유한다.
묶음 내부의 `backend/runtime/saved_poses.json`에도 같은 자세와 대상 Follower ID가 들어 있다.
자세 원본을 수정해도 압축본이나 설치된 Studio가 자동으로 바뀌지는 않는다.

Studio 자체, Docker 이미지·볼륨, 프로젝트·로봇 등록, 보정·카메라 설정, USB 연결, 가상환경, 비밀값, 데이터셋·모델은 이 압축본에 들어 있지 않다.
이 저장소의 `docker-compose.yml`은 관제탑 DB·웹용이며 Studio를 설치하지 않는다.

## 다른 PC에서 준비하기

1. Physical AI Studio와 해당 PC의 Docker/WSL 환경을 별도로 준비한다. 이 묶음의 대상 이미지 revision은 `e5dd66a38cf1e682fdead3ca0fefa60f5bf3459d`다.
2. 로봇·리더·카메라 등록과 해당 장비의 보정을 준비한다. 묶음의 Follower ID는 `bc50f050-d0a5-4430-af97-0486cdaec3a2`이며, 다른 장비나 등록 ID에는 그대로 적용하지 않는다.
3. 같은 장비를 옮긴 경우에도 포트·USB·카메라 경로와 장착 위치를 확인한다. 다른 팔·보정·고정 위치라면 자세를 다시 티칭하거나 호환성을 확인한 뒤 새 묶음을 준비한다.

같은 이미지 revision이라도 이 묶음은 기존 v4 backend 수정본의 해시를 기준으로 한다.
순정 Studio나 다른 수정본에서는 설치 전 원본 해시 검사에 실패할 수 있다. 검사를 제거하지 말고 소스를 비교해 해당 환경용 묶음을 다시 준비한다.

압축을 푼 `bundle/`과 설치 백업은 로컬 작업 파일이므로 Git에서는 계속 제외한다.
컨테이너를 삭제·재생성하거나 Studio를 업데이트하면 확장을 다시 준비·적용해야 한다.
상세 동작과 설치기는 [Studio 확장 안내](../../robot/studio_extension/README.md)를 참고한다.

## 공유 묶음을 갱신할 때

backend/UI를 변경하면 해당 Studio 버전에서 빌드·검증한 `bundle/`을 먼저 준비한다.
묶음의 파일별 해시와 자세 원본의 일치를 확인하고, 저장소 루트에서 아래처럼 압축본과 검증 해시를 갱신한다.

```powershell
tar -cJf outputs/studio_pose_integration/bundle.tar.xz -C outputs/studio_pose_integration bundle
if ($LASTEXITCODE -ne 0) { throw 'Studio archive creation failed' }
$studioHash = (Get-FileHash outputs/studio_pose_integration/bundle.tar.xz -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content outputs/studio_pose_integration/bundle.tar.xz.sha256 "$studioHash  bundle.tar.xz" -Encoding ascii
```

압축본·SHA256·자세 원본과 대응하는 코드를 같은 PR에서 갱신한다.
압축본은 파일당 5MB 이하로 유지하며, `.env`·개인정보·학습 데이터·가중치·백업을 넣지 않는다.
