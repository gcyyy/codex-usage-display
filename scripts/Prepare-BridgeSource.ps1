param([string]$SourceDirectory = (Join-Path (Split-Path $PSScriptRoot -Parent) '.reference\CodexPlusPlus-1.10.0'))
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskSource = [IO.Path]::GetFullPath($SourceDirectory)
$taskInfo = Get-Content (Join-Path $taskRoot 'integration\source.json') -Raw | ConvertFrom-Json
$taskPatch = Join-Path $taskRoot 'integration\codex-plus-1.10.0-usage-bridge.patch'
if ((Get-FileHash -LiteralPath $taskPatch -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskInfo.patchSHA256) {
    throw 'Reviewed bridge patch checksum mismatch.'
}
if (Test-Path -LiteralPath $taskSource) {
    throw 'Source directory already exists. Use the existing reviewed tree, or provide a new empty path.'
}
New-Item -ItemType Directory -Path $taskSource -Force | Out-Null
& git -C $taskSource init
if ($LASTEXITCODE -ne 0) { throw 'Git init failed.' }
& git -C $taskSource config core.autocrlf false
& git -C $taskSource remote add origin $taskInfo.upstream
& git -C $taskSource fetch --depth 1 origin $taskInfo.upstreamCommit
if ($LASTEXITCODE -ne 0) { throw 'Pinned upstream fetch failed.' }
& git -C $taskSource checkout --detach FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw 'Pinned upstream checkout failed.' }
$taskCommit = & git -C $taskSource rev-parse HEAD
if ($taskCommit -ne $taskInfo.upstreamCommit) { throw 'Unexpected upstream commit.' }
& git -C $taskSource apply --check $taskPatch
if ($LASTEXITCODE -ne 0) { throw 'Bridge patch does not apply to pinned source.' }
& git -C $taskSource apply --index $taskPatch
if ($LASTEXITCODE -ne 0) { throw 'Bridge patch application failed.' }
Write-Output 'Pinned public bridge source prepared.'
