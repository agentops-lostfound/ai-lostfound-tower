# Opens the panel in stopped state; never selects or executes a saved pose.
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$python=Join-Path (Split-Path $repo -Parent) '.venv-robot-panel\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) {throw 'Dedicated panel Python missing; see robot/README-panel.md'}
$logs=Join-Path $repo 'outputs/robot_panel_live'
$null=New-Item -ItemType Directory -Force -Path $logs
$existing=@(Get-Process python,pythonw -ErrorAction SilentlyContinue | Where-Object MainWindowTitle -eq 'SO-101 Teaching Pendant | LIVE')
if ($existing.Count -gt 0) {
    Write-Output 'Teaching Pendant LIVE is already open. Switch to that window.'
    exit 0
}
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$process=Start-Process -FilePath $python -ArgumentList @('-m','robot.teaching_gui','--live') `
    -WorkingDirectory $repo -WindowStyle Normal -PassThru `
    -RedirectStandardOutput (Join-Path $logs "panel_$stamp.stdout.log") `
    -RedirectStandardError (Join-Path $logs "panel_$stamp.stderr.log")
Write-Output "Live panel PID: $($process.Id). Starts stopped; no pose is executed automatically."
