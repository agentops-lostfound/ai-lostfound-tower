@echo off
cd /d "%~dp0"
echo Field Vision Beta - http://127.0.0.1:8871
echo Stop server: Ctrl+C
"%~dp0.venv\Scripts\python.exe" -m uvicorn beta.server:app --host 127.0.0.1 --port 8871
pause
