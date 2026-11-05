# Read-only Studio observation subscriber. Never sends robot commands.
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('home','raised','entry','observe')][string]$Pose,
    [string]$Studio='http://localhost:7860',
    [string]$ProjectId='7840975d-960f-4ede-bcca-bd24e4caf24e',
    [string]$FollowerId='bc50f050-d0a5-4430-af97-0486cdaec3a2',
    [string]$OutputRoot='outputs/robot_poses',
    [string]$Note=''
)
$ErrorActionPreference='Stop'
$response=Invoke-RestMethod "$Studio/api/runtime/sessions"
$sessions=@($response | ForEach-Object {$_})
$session=@($sessions | Where-Object follower_id -eq $FollowerId)
if ($session.Count -ne 1 -or $session[0].activity.follower_source -ne 'hold') {
    throw 'Recording requires one existing follower runtime in hold mode. Stop teleoperation in Studio first; this script will not change it.'
}
$uri=($Studio -replace '^http','ws')+"/api/projects/$ProjectId/robots/$FollowerId/observations/ws?fps=5"
$ws=New-Object Net.WebSockets.ClientWebSocket
$cts=New-Object Threading.CancellationTokenSource
$cts.CancelAfter(15000)
$samples=New-Object Collections.Generic.List[object]
$names=@('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')
try {
    $null=$ws.ConnectAsync([uri]$uri,$cts.Token).GetAwaiter().GetResult()
    while ($samples.Count -lt 5) {
        $buffer=New-Object byte[] 65536
        $stream=New-Object IO.MemoryStream
        try {
            do {
                $r=$ws.ReceiveAsync([ArraySegment[byte]]::new($buffer),$cts.Token).GetAwaiter().GetResult()
                if ($r.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) {throw 'Observation socket closed'}
                $stream.Write($buffer,0,$r.Count)
            } while (-not $r.EndOfMessage)
            $msg=[Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
        } finally {$stream.Dispose()}
        if ($msg.event -eq 'error') {throw ($msg | ConvertTo-Json -Compress)}
        if ($msg.event -ne 'observation') {continue}
        foreach ($name in $names) {
            $v=$msg.data.PSObject.Properties["$name.pos"].Value
            if ($null -eq $v -or $v -is [bool] -or [double]::IsNaN([double]$v) -or [double]::IsInfinity([double]$v)) {throw "Missing/invalid joint $name"}
        }
        $samples.Add([ordered]@{received_at=[DateTimeOffset]::Now.ToString('o'); joints=$msg.data})
    }
} finally {$ws.Dispose();$cts.Dispose()}
$ranges=[ordered]@{}
foreach ($name in $names) {
    $values=@($samples | ForEach-Object {[double]$_.joints.PSObject.Properties["$name.pos"].Value})
    $m=$values | Measure-Object -Minimum -Maximum
    $ranges[$name]=$m.Maximum-$m.Minimum
}
$stable=@($ranges.Values | Where-Object {$_ -gt 1.0}).Count -eq 0
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss_fff'
$dir=Join-Path $OutputRoot "$stamp`_$Pose"
$null=New-Item -ItemType Directory -Path $dir
$record=[ordered]@{
    schema='manual_pose_sample.v1';pose=$Pose;follower_id=$FollowerId
    unit='studio_normalized';samples=$samples.ToArray();joint_range=$ranges
    stable_within_1_normalized_unit=$stable
    note=$Note;runtime_source_before_capture='hold'
    valid_for_automatic_motion=$false;collision_clearance_verified=$false
    image_synchronized=$false;target_xyz_mm=$null;robot_motion_command_sent=$false
}
$file=Join-Path $dir 'pose.json'
[IO.File]::WriteAllText([IO.Path]::GetFullPath($file),($record|ConvertTo-Json -Depth 10),(New-Object Text.UTF8Encoding($false)))
Write-Output "Saved: $file"
Write-Output "Stable observations: $stable (does not verify geometry or collision clearance)"
