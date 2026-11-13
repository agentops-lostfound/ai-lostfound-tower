> **과거 게시 스냅샷의 기록입니다.** 최신 로컬 인계는 v1.0.10입니다. [현재 팀 공유 자료](2026-11-13-publication-plan.md)를 먼저 읽으세요. 아래 본문은 당시 코드·계획을 보존한 것이며 최신 원본 문서의 복사본이 아닙니다.

> 게시 결정 갱신: 사용자가 브랜치명을 `pil2ya_02`로 직접 지정했습니다. Jira 번호는 미제공이며 생성하지 않습니다. 저장 위치는 `robot/field_vision/`, 코드 기준은 v0.2.80입니다. 장치 번호/프로젝트 ID는 환경변수로 전환했고 사진과 정적 보정/집기 JSON은 제외했습니다. 아래는 Claude의 v0.2.77 당시 계획으로, 현재 결정과 다른 부분은 이 갱신을 우선합니다.

# 팀 GitHub 업로드 계획 — Field Vision 통합 베타 (2026-11-12 갱신)

사용자 결정(11-12): 지금까지의 Field Vision 작업(`new_robot`)을 **팀 GitHub 저장소에 새 브랜치를 만들어** 올린다. 실제 업로드는 Codex가 이 문서 순서대로 진행한다. Claude는 이 문서만 작성했고 git 명령(브랜치·커밋·push·PR)은 실행하지 않았다.

## 1. 대상
- 팀 저장소: `https://github.com/agentops-lostfound/ai-lostfound-tower` (기본 브랜치 `main`, 직접 push 금지)
- 로컬 사본: `<팀 저장소 폴더>`
  - **주의:** 11-12 기준 이 사본은 다른 업무 브랜치(`LF-19-sunpil-training-integration`)에 있다. 커밋하지 않은 변경도 있다(`robot/README*.md` 3개 수정, `docs/reports/2026-11-10-studio-stop-home-report.md` 미추적). 이 변경을 건드리거나 지우지 않는다. 브랜치 전환·stash·reset 대신 아래 3절처럼 **별도 작업 폴더(git worktree)** 를 쓴다.
- 올릴 원본: `<Field Vision 폴더>` (git 저장소 아님)

## 2. 사용자에게 먼저 확인할 것 (Codex)
팀 규칙(`CONTRIBUTING.md`)상 브랜치 이름은 `LF-번호-이름-짧은-영문-설명`이다. 아래 세 가지는 추측하지 말고 사용자에게 묻는다.
1. **Jira 업무 번호(LF-번호)**
2. **브랜치용 영문 이름**: CONTRIBUTING.md 표에는 jaewon / geontae / soonpil / yeonwoo / jaemin이 있다. 사용자가 이 표에 없으면 어떤 이름을 쓸지 묻는다.
3. **저장소 안 위치**: 추천은 `robot/field_vision/`이다. `robot/`가 SO-101 로봇팔 폴더이고, 기존 `robot/` 파일은 하나도 고치지 않는다. 다른 위치를 원하면 그 위치로 한다.

예시(번호·이름 확정 후): 브랜치 `LF-<번호>-<이름>-field-vision-beta`, 커밋 `LF-<번호> Field Vision 통합 베타 v0.2.77 — 탑뷰 YOLO 단독 판정, ARM 검출 박스 경계, 넓은 물품 밀착 집기`

## 3. 진행 순서
```powershell
cd <팀 저장소 폴더>
git fetch origin
# 현재 사본의 브랜치·미커밋 변경은 그대로 두고, 최신 main 기준 별도 폴더에서 작업
git worktree add ..\ai-lostfound-tower-fv -b LF-<번호>-<이름>-field-vision-beta origin/main
cd ..\ai-lostfound-tower-fv
```
1. 대상 폴더(예: `robot/field_vision/`)를 만들고 아래 4절 "포함" 목록만 복사한다. 원본의 폴더 구조(`beta/`, `docs/` 등)는 그대로 유지한다. `beta/config.py`의 데이터 경로가 `beta` 폴더 기준 상대 경로라, 위치를 옮겨도 동작한다.
2. 대상 폴더에 `.gitignore`를 만들어 `beta_data/`, `models/`, `.venv/`, `.omc/`, `__pycache__/`, `*.log`를 막는다. 팀 루트 `.gitignore`에는 `beta_data/`가 없다.
3. 5절 민감 정보 점검을 한다.
4. 검증(6절)을 한다.
5. `git add robot/field_vision` → `git status`로 포함 파일과 용량을 확인한다(가중치·DB·사진이 없어야 한다) → 커밋한다(한국어, `LF-번호 …` 형식).
6. `git push -u origin <브랜치>` → GitHub에서 Pull Request를 연다. 양식은 `.github/pull_request_template.md`(Jira 업무 / 바꾼 내용 / 확인 방법)를 따른다.
7. PR 본문에 적을 것: 새 폴더만 추가하고 기존 파일은 고치지 않았다는 점, 버전(v0.2.77), 핵심 기능(TEAM_HANDOFF_20261112.md "실행 가능한 현재 기능"), 실물 미검증 항목(넓은 물품 밀착, 놓기까지 끝까지 완료), 가중치·데이터는 저장소 밖에 있다는 점.
8. `robot/` 담당 폴더에 새 폴더를 추가하는 것이므로 #2조 채널에 한 줄 알린다(CONTRIBUTING.md 3절).
9. 병합은 사용자가 결정한다. Codex가 임의로 병합하지 않는다. `git push --force`, `git reset --hard` 후 push는 쓰지 않는다.
10. 끝나면 작업 폴더를 정리한다: `git worktree remove ..\ai-lostfound-tower-fv`(push가 끝난 뒤).

## 4. 포함·제외
**포함** (`new_robot` 기준)
- `beta/` 전체 소스·테스트·`beta/static/`·`beta/assets/`·`beta/requirements.txt` (단, `__pycache__/` 제외)
- `docs/` 전체(일지·진행 기록·측정 문서)
- `README.md`, `BETA_README.md`, `TEAM_HANDOFF_20261110.md`, `TEAM_HANDOFF_20261112.md`
- `requirements.txt`, `requirements-lock.txt`, `Start-Beta.cmd`, `start-beta.ps1`

**제외**
- `.venv/`, `.omc/`(수정 전 스냅샷), `__pycache__/`
- `beta_data/`(약 1.1GB: 등록 DB `vision.sqlite3`, 물품 사진 `media/`, 집기 기록 `grasp_trials/`, 학습 데이터 `detector_dataset/`, 보관함·손가락·HOME·놓기 보정값). 등록 메모에 실제 사람 이름이 들어 있다.
- `models/`(YOLO 가중치 약 56MB). 공유가 필요하면 팀 규칙대로 저장소 밖(Hugging Face Hub 등)으로 전달한다.
- `work/`, `dist/`, `Test_IMG/`(실험 스크립트 결과·사진·캡처), `Start_new_robot.txt`(개인 PC 경로)

## 5. 민감 정보 점검 (올리기 전에)
- 11-12 Claude 점검 결과: 소스에 비밀값·토큰·내부망 주소는 없었다. 테스트 데이터에 있던 실제 사람 이름은 가명으로 바꿨다(`beta/test_registry_edit.py`).
- 남아 있는 로봇 장치 일련번호 `팔로워 일련번호`(`beta/robot_link.py`, `robot_actions.py`, `robot_frame.py`, `reproduction.py`)는 비밀값은 아니지만 이 로봇 전용 값이다. 그대로 둘지 사용자에게 확인하고 PR 본문에 적는다.
- 복사한 뒤 대상 폴더에서 다시 확인한다: `<로컬 작업 폴더>`, `10.10.`, `192.168.`, 토큰·키 문자열, 사람 이름, `.jpg/.png/.sqlite3/.pt` 파일 포함 여부. `beta/assets/`의 샘플 사진은 팀 외부 공개가 가능한지 확인한다.

## 6. 검증
- 원본 PC(`new_robot/.venv`)에서: `python -m unittest beta.test_<모듈>`을 모듈별로 돌린다. `test_robot_actions`, `test_grasp_flow`는 원래 고장이라 제외한다. v0.2.77 기준 나머지는 모두 통과했다.
- `node --check beta/static/beta.js`
- 팀 CI(`.github/workflows/tests.yml`)는 저장소 루트 `tests/`만 실행하고 `agents/requirements.txt`만 설치한다. 그래서 새 폴더의 테스트는 CI에서 돌지 않고 CI를 깨뜨리지도 않는다. torch·ultralytics가 필요한 테스트라 `tests/`로 옮기지 않는다. PR이 CI를 통과하는지만 확인한다.

## 7. 원칙 (11-10 계획에서 유지)
- 과거 시점의 중간 구현을 복원한 것처럼 꾸미거나, 현재 소스를 여러 과거 시각 커밋으로 나누지 않는다. 현재 최종본을 커밋하고, 시간대별 내역은 `docs/progress/` 문서로 남긴다.
- 업로드 후에도 실제 개발·실행은 당분간 `new_robot` 폴더에서 계속된다. 팀 브랜치에 추가 반영할 때는 같은 포함·제외 목록으로 다시 복사하고, 버전 번호로 어느 시점인지 적는다.
