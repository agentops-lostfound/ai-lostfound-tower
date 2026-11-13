# 새 PC에서 관제탑 다시 세우기 (2026-11-13)

한줄 설명: 11/13 발표가 끝나 교육원 관제탑 PC를 비웠다. 이 문서는 **다른 PC에서 저장소만 받아 관제탑을 안전하게 다시 켜는 순서**를 위에서 아래로 따라 하게 적은 것이다.

- 기준: main(PR #279 병합 뒤). 명령은 Windows PowerShell 기준
- 가장 중요한 원칙: **처음에는 가상 팔(`sim`)로만 켠다.** 실물 로봇 값은 넣지 않는다(7장)
- 용어
  - 가상 시연: 카메라·로봇 없이 관제탑이 가짜 보관함과 가짜 팔로 전체 흐름을 돌리는 모드(`TOWER_SIM=1`)
  - `.env`: 비밀값(토큰·웹후크·키)을 적는 파일. 저장소에 올리지 않는다
  - 가상환경(`.venv`): 이 저장소 전용 파이썬 패키지 방

## 0. 저장소에 있는 것 / 없는 것

| 있는 것(받으면 됨) | 없는 것(다시 준비해야 함) |
|---|---|
| 관제탑 코드·화면·시험, 문서 전부 | `.env` 의 값 전부 — 교육원 PC의 `.env` 는 11/13 지웠고 사본이 없다 |
| 팀 DB 표 정의(`center/schema.sql`, `center/migrations/`) | 팀 DB 안의 기록(시연 물건·접수 기록) — 새 PC에서는 빈 DB로 시작 |
| 발표 덱 원본(`docs/presentation/deck/project/`) | 덱에 넣은 영상 파일 — 덱 아티팩트에만 있음 |
| Mi:dm 등록 파일(`docs/ollama/`) | 모델 파일(Mi:dm, Qwen3-VL) — 처음 실행할 때 다시 내려받음(수 GB) |
| 저장 자세·티칭 값(`robot/`) | 로봇 PC 쪽 설정·원격 토큰 — 로봇 담당(김건태)에게 확인 |

## 1. 준비할 프로그램

| 프로그램 | 꼭 필요한가 | 확인 명령 |
|---|---|---|
| Python 3.11 ~ 3.13 | 필수 | `python --version` |
| Git | 필수 | `git --version` |
| Docker Desktop | 팀 DB를 쓸 때(없어도 가상 시연은 됨) | `docker info` |
| Ollama | 챗봇·에이전트 설명에 실제 모델을 쓸 때 | `ollama --version` |
| NVIDIA 그래픽카드 | Qwen 사진 분석을 쓸 때 | `nvidia-smi` |

## 2. 저장소 받기 → 가상환경 → 패키지

Windows 터미널 → PowerShell 탭에서:

```
mkdir C:\git -Force; cd C:\git
git clone https://github.com/agentops-lostfound/ai-lostfound-tower.git
cd ai-lostfound-tower
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r agents/requirements.txt
```

- `Activate.ps1` 이 막히면: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` → `Y`
- 예전 안내 `docs/setup-windows.md` 는 11월 초 비전 실험 기준이라 관제탑에는 이 문서를 따른다

## 3. `.env` 만들기

```
copy .env.example .env
notepad .env
```

**가상 시연만 볼 때는 `TOWER_SIM=1` 한 줄만 있으면 된다.** 나머지는 쓸 기능이 생길 때 채운다.

| 값 이름 | 쓰는 곳 | 다시 받는 곳 |
|---|---|---|
| `TOWER_SIM` | 가상 시연 켜기 | 직접 `1` |
| `POSTGRES_PASSWORD`, `DATABASE_URL` | 팀 DB | 비우면 시연용 기본값으로 동작 |
| `DISCORD_WEBHOOK_*` | 관제 채널 알림 | 디스코드 채널 설정 → 연동 → 웹후크 → 새로 만들기 |
| `DISCORD_BOT_TOKEN` | 분실물봇 | 디스코드 개발자 포털 → 봇 → 토큰 다시 만들기 |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` | 챗봇 실행 기록 | Langfuse 프로젝트 설정 → API 키 |
| `OPENROUTER_API_KEY`, `HF_TOKEN` | 외부 모델·Hugging Face | 각 사이트 계정 설정 |
| `TOWER_KIOSK_CAMERAS` | 키오스크 서버 카메라 | 6장 카메라 번호 찾기 |
| `TOWER_ROBOT_*`, `TOWER_REMOTE_ROBOT_*` | **실물 로봇** | 넣지 않는다(7장). 필요하면 로봇 담당에게 |

- 교육원 PC에 있던 토큰·웹후크는 그 PC에서 지웠지만, **같은 값을 다시 쓰지 말고 새로 만들어** 옛 값은 폐기하는 편이 안전하다
- `.env` 는 읽어 주거나 출력하거나 커밋하지 않는다(`CLAUDE.md` 비밀값 규칙)

## 4. 먼저 시험

```
python -m unittest discover -s tests
```

- 마지막 줄이 `OK` 면 정상(11/13 기준 약 2,000개, 2분쯤)
- `tkinter` 가 없는 환경에서는 그와 관련된 오류 9개가 날 수 있다(11/13 클라우드에서 확인, 관제탑 동작과는 무관)

## 5. 켜기 — 가상 팔로

### 5-1. 가장 단순한 방법 (Docker 없이)

```
$env:TOWER_SIM="1"; $env:TOWER_SIM_DB="0"
python -m uvicorn agents.api:app --host 127.0.0.1 --port 8100
```

### 5-2. 평소 방법 (팀 DB 포함, Docker Desktop 켠 뒤)

```
.\tools\start_tower.bat sim
```

- `sim`: `.env` 에 실물 로봇 값이 있어도 이번 실행은 가상 팔. 켤 때 `[ROBOT] 가상 로봇 모드` 한 줄이 나온다
- `lan` 을 붙이면 같은 네트워크의 누구나 직원 화면까지 열 수 있다. 태블릿을 쓸 때만 붙이고, 끝나면 `lan` 없이 다시 켠다
- 끄기: 그 창에서 【Ctrl】+【C】 한 번

### 5-3. 열어 볼 화면 (브라우저)

| 주소 | 화면 |
|---|---|
| `http://127.0.0.1:8100/showcase` | 통합 시연(키오스크·휴대폰·DB 기록·에이전트 흐름) |
| `http://127.0.0.1:8100/kiosk?machine=KIOSK-A&demo=1` | 역 키오스크(카메라 없이) |
| `http://127.0.0.1:8100/lost` | 분실인 휴대폰 웹 |
| `http://127.0.0.1:8100/kiosk?machine=CENTER` | 본센터 키오스크(회수) |
| `http://127.0.0.1:8100/live` | 보관함·가상 팔 실시간 |
| `http://127.0.0.1:8100/health` | 상태 확인(가상 부품 이름이 `Sim…` 으로 나오면 가상 모드) |

한 바퀴 흐름과 막혔을 때 대체는 `docs/design/demo_checklist.md` 를 그대로 따른다.

## 6. 필요할 때만 붙이는 것

| 기능 | 순서 | 안내 |
|---|---|---|
| 챗봇 실제 모델(Mi:dm) | Ollama 설치 → `docs/ollama/` 에서 `ollama create midm-2.0-mini -f Modelfile.midm-2.0-mini` | `docs/ollama/README.md` |
| 키오스크 사진 분석(Qwen) | `tools\setup_qwen.bat`(처음 6~8GB 내려받음) → `.\.venv-qwen\Scripts\python.exe tools\intake_qwen_worker.py` | `docs/design/virtual_demo.md` 4-5 |
| 키오스크 서버 카메라 | 관제탑 끈 상태에서 `python tools/list_cameras.py` → `.env` `TOWER_KIOSK_CAMERAS=KIOSK-A=번호` | `web/README.md` 키오스크 카메라 설정 |
| 챗봇 실행 기록(Langfuse) | `python tools/langfuse_setup.py --check` → `--push-prompts` | `docs/design/chatbot_sllm_rag.md` 11장 |
| 분실물봇(디스코드) | `pip install -r tools/requirements-bot.txt` → `python tools/lostfound_bot.py`(디스코드 없이 `--try "메시지"`) | `docs/design/virtual_demo.md` |
| 환경 점검 한 번에 | `python tools/check_ai_env.py` | 출력의 ✅/⚠️/❌ |

## 7. 안전 수칙

1. **실물 로봇**: `.env` 에 `TOWER_ROBOT_SEQUENCE=taught` 등 실물 값을 넣으면 본센터 키오스크 회수와 [직원 확인 후 진행]이 진짜 로봇을 움직인다. 로봇 옆에서 정지 수단을 확인한 사람이 있을 때만 넣는다. 순서는 `docs/handoff/2026-11-10-showcase-taught-robot.md`
2. **지우는 도구**(`purge_items.py`, `purge_sim_items.py`, `reset_demo.py`)는 옵션 없이 먼저 실행해 미리보기를 본 뒤 `--apply`. 되돌릴 수 없다
3. **비밀값**은 `.env` 에만. 문서·메신저·커밋에 쓰지 않는다. 토큰 모양 문자열이 있으면 GitHub가 push를 막는다
4. **main 에 직접 push 하지 않는다.** 업무 하나 = 브랜치 하나(`LF-번호-이름-영문-설명`) → PR → 자동 시험 통과 뒤 병합
5. 코드를 바꾸면 4장의 시험을 다시 돌린다

## 8. PC를 떠날 때 (11/13 교육원 PC에서 한 순서)

1. 올리지 않은 변경 확인: `git status`, `git log --oneline --branches --not --remotes` → 필요한 것은 브랜치로 올리거나 패치로 보관
2. 저장소 폴더 삭제(`.env`·`.venv`·모델 포함)
3. 로그아웃: GitHub(`gh auth logout`, Windows 자격 증명 관리자의 `git:https://github.com`), Claude Code(`/logout`), 브라우저(쿠키·저장된 비밀번호), 메신저, VS Code
4. Docker Desktop 에서 팀 DB 컨테이너와 볼륨 삭제
5. 떠난 PC에 있던 토큰·웹후크는 다시 만들어 옛 값을 폐기

## 9. 더 읽을 문서

- 관제탑 전체 구조·이어받기: `docs/design/tower_handover.md`
- 가상 시연 자세히: `docs/design/virtual_demo.md`
- 화면 지도: `web/README.md`
- 챗봇 구조: `docs/design/chatbot_agents.md`
- 로봇 연결 약속: `docs/contracts/robot_api.md`, `docs/contracts/robot_db_target.md`
- 발표 덱 이어 고치기: `docs/presentation/HANDOFF.md`

## 확인한 것 / 확인하지 못한 것

- 실제로 실행해 확인(11/13, 리눅스 클라우드 환경): 5-1 방식으로 켜서 5-3의 주소 6개와 `/staff`, `/docs` 가 모두 열림(200), `/health` 에 가상 부품(`SimTopview`, `SimWorld`)이 나옴
- 확인하지 못함: 이 문서의 PowerShell 명령을 **빈 Windows PC에서 처음부터** 돌려 보지는 않았다. 2장 패키지 설치, 5-2 `start_tower.bat sim`, 6장 선택 기능은 기존 문서와 스크립트 내용을 근거로 적었다. 새 PC에서 막히면 이 문서 아래에 증상과 해결을 덧붙인다
