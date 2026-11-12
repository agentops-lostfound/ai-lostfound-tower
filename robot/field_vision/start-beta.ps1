$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'Field Vision Beta · http://127.0.0.1:8871'
Write-Host '종료: Ctrl+C / 장비 연결 후 실제 로봇 제어 가능'
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn beta.server:app --host 127.0.0.1 --port 8871
