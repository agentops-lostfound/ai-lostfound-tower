# Physical AI Studio 공유 파일과 설치 순서

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

## 압축 확인과 해제

PowerShell에서 **이 저장소 루트**로 이동한 뒤 실행한다. 이 단계는 Studio를 재시작하거나 로봇을 연결하지 않는다.

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

이후 `outputs/studio_pose_integration/bundle/bundle.json`과 `backend/`, `dist/`가 생긴다.
압축을 푼 `bundle/`은 로컬 작업 파일이므로 Git에서는 계속 제외한다.

## 설치 전 점검과 적용

저장소 루트의 PowerShell에서 읽기 전용 점검을 실행한다. 아래 명령은 WSL 배포판 `Ubuntu-24.04`와 컨테이너 `physical-ai-studio-cuda`를 기준으로 한다.

```powershell
wsl -d Ubuntu-24.04 --cd "$PWD" -- python3 robot/studio_extension/install.py --bundle outputs/studio_pose_integration/bundle
```

점검은 압축 내부 파일 해시·실행 이미지 revision·활성 세션·필요 장치 경로를 확인한다.
기존 backend 원본 해시 대조는 실제 적용 단계에서 파일을 쓰기 전에 수행된다.
장치를 준비하고 활성 로봇 세션을 종료한 상태에서 [설치·백업·복구 안내](../../robot/studio_extension/README.md#설치-준비-및-적용)에 따라 `--apply`로 적용한다.

이미 확장이 설치된 이 PC에는 초기 설치기를 다시 실행하지 않는다. 이전 설치본의 갱신은 현재 소스 비교와 별도 백업이 필요하다.
컨테이너를 삭제·재생성하거나 Studio를 업데이트하면 확장을 다시 준비·적용해야 한다.
실제 장비 연결·이동 검증은 별도 단계이며, 이 공유 작업에서는 수행하지 않는다.

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
