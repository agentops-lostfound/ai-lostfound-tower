# Separate clone and venvs; never updates an existing checkout or robot installation.
[CmdletBinding()]
param(
    [string]$Destination = 'C:\00lsp\T_prj_edge\ai-lostfound-vision-trial',
    [switch]$LoadModel
)
$ErrorActionPreference = 'Stop'
function Run-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe" }
}
Get-Command git -ErrorAction Stop | Out-Null
Get-Command py -ErrorAction Stop | Out-Null
Run-Checked py @('-3.11', '-c', 'import sys; print(sys.version)')
if (Test-Path -LiteralPath $Destination) {
    throw 'Destination already exists. Choose a new empty path; existing files are never replaced.'
}
$parent = Split-Path -Parent $Destination
New-Item -ItemType Directory -Force -Path $parent | Out-Null
Run-Checked git @('clone', '--branch', 'LF-3-yolo-aruco', '--single-branch', 'https://github.com/agentops-lostfound/ai-lostfound-tower.git', $Destination)
Push-Location $Destination
try {
    # Reproducible source version reviewed on 2026-11-04.
    Run-Checked git @('switch', '--detach', '51600043c02a181178ee052644ccad1514559e4d')
    Run-Checked py @('-3.11', '-m', 'venv', '.venv-vision')
    Run-Checked py @('-3.11', '-m', 'venv', '.venv-qwen')
    $vision = Join-Path $Destination '.venv-vision\Scripts\python.exe'
    $qwen = Join-Path $Destination '.venv-qwen\Scripts\python.exe'
    Run-Checked $vision @('-m', 'pip', 'install', '-r', 'vision/requirements_inference.txt')
    Run-Checked $qwen @('-m', 'pip', 'install', '-r', 'qwen/requirements.txt')
    Run-Checked $vision @('-m', 'vision.scripts.test_vision', '--check-environment')
    Push-Location qwen
    try {
        $check = @('-m', 'scripts.check_environment')
        if ($LoadModel) { $check += '--load-model' }
        Run-Checked $qwen $check
    } finally { Pop-Location }
    Write-Host "Prepared source and environments: $Destination"
    Write-Host 'Photo inference and actual accuracy are not yet tested. Follow docs/setup-vision-trial-windows.md in the pil2ya checkout.'
} finally { Pop-Location }
