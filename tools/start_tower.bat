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
rem 11/5: "start_tower.bat lan" 으로 켜면 같은 교육원 네트워크의 다른 PC 에서도 접속된다(0.0.0.0). 기본은 이 PC 안에서만(127.0.0.1)
rem   다른 PC 에서 열려면 방화벽 허용 규칙도 필요(관리자 PowerShell, 안내 docs/design/virtual_demo.md). 로그인이 없으니 시험할 때만 쓴다
set TOWER_HOST=127.0.0.1
if /i "%~1"=="lan" set TOWER_HOST=0.0.0.0
if "%TOWER_HOST%"=="0.0.0.0" echo [주의] 같은 네트워크의 누구나 접속할 수 있습니다(직원 화면 포함, 로그인 없음). 시험이 끝나면 Ctrl+C 후 기본으로 다시 켜세요
echo [2/2] 관제탑 API 켜기: http://127.0.0.1:8100/docs  (끄기: Ctrl+C 또는 창 닫기)
rem --no-access-log: 요청마다 쓰는 로그를 끈다. 이 창 안을 클릭하면 Windows 가 '선택' 모드로 바꿔, 로그를 쓰는 순간 API 가 멈춘다(11/3 겪음). 멈췄으면 Esc
python -m uvicorn agents.api:app --host %TOWER_HOST% --port 8100 --no-access-log
pause
