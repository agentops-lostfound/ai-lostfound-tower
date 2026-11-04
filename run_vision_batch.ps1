# LF-3 real-image batch evaluation: camera images -> YOLO/ArUco -> Qwen -> Adapter -> CompositeBackend.
# Read-only for source photos; no robot/DB/matcher calls. Each image starts a fresh inference sequence.
param(
    [string]$ImageDir = 'C:\Users\user\Pictures\Camera Roll',
    [string]$RepoDir = 'C:\Users\user\AI-LostFound\team-repo',
    [int]$Limit = 0,
    [string]$Device = 'cpu'
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $RepoDir
$python = (Resolve-Path -LiteralPath '..\.venv-vision\Scripts\python.exe').Path
$runner = Join-Path (Get-Location).Path 'run_vision_adapter_full.py'
$qwenPython = (Resolve-Path -LiteralPath '..\qwen\.python\cpython-3.11.18-windows-x86_64-none\python.exe').Path
$qwenRoot = (Resolve-Path -LiteralPath '.\qwen').Path
$qwenSite = (Resolve-Path -LiteralPath '..\qwen\.venv\Lib\site-packages').Path
$qwenCache = (Resolve-Path -LiteralPath '..\qwen\.cache\huggingface').Path
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) { throw "Missing runner: $runner" }
if (-not (Test-Path -LiteralPath $ImageDir -PathType Container)) { throw "Missing image directory: $ImageDir" }

$images = @(Get-ChildItem -LiteralPath $ImageDir -File | Where-Object { $_.Extension.ToLowerInvariant() -in @('.jpg','.jpeg','.png','.bmp','.webp') } | Sort-Object Name)
if ($Limit -gt 0) { $images = @($images | Select-Object -First $Limit) }
if ($images.Count -eq 0) { throw 'No images found in ImageDir (top-level files only).' }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$batchDir = Join-Path (Get-Location).Path "outputs\batch_vision_$stamp"
New-Item -Path $batchDir -ItemType Directory -Force | Out-Null
$results = [System.Collections.Generic.List[object]]::new()
Write-Host "Images: $($images.Count) | Input: $ImageDir | Logs: $batchDir"

foreach ($i in 0..($images.Count - 1)) {
    $img = $images[$i]
    $log = Join-Path $batchDir ("{0:D3}.log" -f ($i+1))
    Write-Host ("[{0}/{1}] {2}" -f ($i+1),$images.Count,$img.Name)
    $start = Get-Date
    $output = & $python $runner --image $img.FullName --qwen-root $qwenRoot --qwen-python $qwenPython --qwen-site-packages $qwenSite --qwen-cache-dir $qwenCache --device $Device 2>&1
    $exitCode = $LASTEXITCODE
    $output | Out-File -LiteralPath $log -Encoding utf8
    $reportLine = @($output | Select-String -Pattern '^\[REPORT\]\s+(.+)$' | Select-Object -Last 1)
    $reportPath = if ($reportLine.Count) { $reportLine[0].Matches[0].Groups[1].Value.Trim() } else { '' }
    $modelStatus = ''
    $count = ''
    $adapterCount = ''
    $categories = ''
    $calibration = ''
    if ($reportPath -and (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        try {
            $r = Get-Content -LiteralPath $reportPath -Raw -Encoding utf8 | ConvertFrom-Json
            $modelStatus = $r.sequence.status
            $count = @($r.objects).Count
            $calibration = [string]$r.calibration.valid
            $inspectionPath = Join-Path (Split-Path -Parent $reportPath) 'adapter_handshake_inspection.json'
            if (Test-Path -LiteralPath $inspectionPath -PathType Leaf) {
                $a = Get-Content -LiteralPath $inspectionPath -Raw -Encoding utf8 | ConvertFrom-Json
                $adapterCount = @($a.inspection_detections).Count
                $categories = (@($a.inspection_detections | ForEach-Object { $_.features.category }) -join '|')
            }
        } catch { Write-Warning "Failed to parse JSON for $($img.Name): $_" }
    }
    $seconds = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
    $results.Add([PSCustomObject]@{
        image=$img.Name; exit_code=$exitCode; sequence_status=$modelStatus
        yolo_objects=$count; adapter_objects=$adapterCount; categories=$categories
        calibration_valid=$calibration; elapsed_seconds=$seconds
        result_json=$reportPath; log=$log
    })
    $results | Export-Csv -LiteralPath (Join-Path $batchDir 'summary.csv') -NoTypeInformation -Encoding utf8
    Write-Host ("  Exit={0} | Detected={1} | Adapted={2} | {3}s" -f $exitCode,$count,$adapterCount,$seconds)
}
Write-Host "Batch complete: $(Join-Path $batchDir 'summary.csv')"
Write-Host "Robot, DB and matching were NOT invoked. Review images/JSON for real accuracy."
