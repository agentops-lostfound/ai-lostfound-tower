@echo off
rem AI 분실물 관제탑 켜기 — 팀 DB(docker) + 관제탑 API(포트 8100)
rem 더블클릭하거나 시작 프로그램 폴더(shell:startup)에 바로가기를 두면 로그인할 때 자동으로 켜진다
rem 이 창을 닫으면 API 가 꺼진다(DB 는 docker 가 계속 켜 둠)
chcp 65001 >nul
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
echo [1/2] 팀 DB 켜기 (Docker Desktop 이 켜져 있어야 함)
docker compose up -d
echo [2/2] 관제탑 API 켜기: http://127.0.0.1:8100/docs  (끄기: Ctrl+C 또는 창 닫기)
python -m uvicorn agents.api:app --host 127.0.0.1 --port 8100
pause
