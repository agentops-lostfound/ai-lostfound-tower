@echo off
rem AI 분실물 관제탑 켜기 — 팀 DB(docker) + 관제탑 API(포트 8100)
rem 더블클릭하거나 시작 프로그램 폴더(shell:startup)에 바로가기를 두면 로그인할 때 자동으로 켜진다(Docker Desktop 준비를 기다린 뒤 DB 를 켬)
rem 이 창을 닫으면 API 가 꺼진다(DB 는 docker 가 계속 켜 둠). 창 안은 클릭하지 말고 최소화만 한다
chcp 65001 >nul
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
echo [1/2] 팀 DB 켜기 (Docker Desktop 준비를 최대 2분 기다림)
set /a tries=0
:wait_docker
docker info >nul 2>&1 && goto docker_ready
set /a tries+=1
if %tries% geq 24 (
  echo Docker Desktop 이 2분 안에 준비되지 않았습니다. API 는 켜지만 DB 기록은 Docker 가 켜진 뒤부터 됩니다
  goto start_api
)
timeout /t 5 /nobreak >nul
goto wait_docker
:docker_ready
docker compose up -d
rem DB 바뀐 점 적용(center/migrations) + 인계 완료 30일 지난 습득자 연락처 지우기(실패해도 API 는 켬)
python tools\db_migrate.py --apply --wait 60
python tools\purge_contacts.py --apply
:start_api
rem Options (11/5, any order): "lan" = 0.0.0.0 (see docs/design/virtual_demo.md 4-2-1), "dev" = auto restart when agents/robot/discord_ops .py change, "nodb" = virtual demo does not write the team DB
rem ASCII only on these lines: Korean here shifts cmd's UTF-8 line positions and breaks the next echo (11/5)
set TOWER_HOST=127.0.0.1
set TOWER_RELOAD=
for %%a in (%*) do if /i "%%a"=="lan" set TOWER_HOST=0.0.0.0
for %%a in (%*) do if /i "%%a"=="dev" set TOWER_RELOAD=--reload --reload-dir agents --reload-dir robot --reload-dir discord_ops
rem 11/10 Virtual demo (TOWER_SIM=1) also saves every record to the team DB (agents/db_mirror.py). Default on. "nodb" = memory only.
set TOWER_SIM_DB=1
for %%a in (%*) do if /i "%%a"=="nodb" set TOWER_SIM_DB=0
if "%TOWER_SIM_DB%"=="0" echo [NODB] Virtual demo keeps records in memory only (team DB is not written).
if "%TOWER_HOST%"=="0.0.0.0" echo [WARN] LAN mode: anyone on this network can open all pages incl. staff (no login). Test only, then restart without lan.
if defined TOWER_RELOAD echo [DEV] Auto restart on code change (virtual demo memory resets each restart). Use plain start_tower.bat for the final demo.
echo [2/2] 관제탑 API 켜기: http://127.0.0.1:8100/docs  (끄기: Ctrl+C 또는 창 닫기)
rem --no-access-log: 요청마다 쓰는 로그를 끈다. 이 창 안을 클릭하면 Windows 가 '선택' 모드로 바꿔, 로그를 쓰는 순간 API 가 멈춘다(11/3 겪음). 멈췄으면 Esc
rem 11/9 Ctrl+C hang fix: kiosk camera stream (MJPEG) never ends, so uvicorn waited forever. Force close after 3s if supported.
set TOWER_GRACE=
python -m uvicorn --help 2>nul | findstr /c:"timeout-graceful-shutdown" >nul && set TOWER_GRACE=--timeout-graceful-shutdown 3
python -m uvicorn agents.api:app --host %TOWER_HOST% --port 8100 --no-access-log %TOWER_RELOAD% %TOWER_GRACE%
pause
