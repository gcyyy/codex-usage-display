param([string]$State)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskExe = Join-Path $taskRoot 'codex-usage-collector.exe'
if (-not (Test-Path -LiteralPath $taskExe)) { $taskExe = Join-Path $taskRoot 'dist\codex-usage-collector.exe' }
if (-not (Test-Path -LiteralPath $taskExe)) { throw 'Missing collector executable.' }
if (-not $State) { $State = Join-Path (Split-Path $taskExe -Parent) '.runtime' }
$taskState = [System.IO.Path]::GetFullPath($State)
if ($taskState.Contains('"')) { throw 'Invalid state path.' }
& $taskExe --state $taskState init
if ($LASTEXITCODE -ne 0) { throw 'Configuration failed.' }
# Health authentication stays inside the collector; no secret is loaded by PowerShell.
$taskHealth = & $taskExe --state $taskState diagnose 2>$null
if ($LASTEXITCODE -eq 0) { Write-Output 'Collector already running.'; return }
$taskProcess = Start-Process -FilePath $taskExe -ArgumentList @('--state', ('"' + $taskState + '"'), 'serve') -WindowStyle Hidden -PassThru
for ($taskAttempt = 0; $taskAttempt -lt 10; $taskAttempt++) {
    Start-Sleep -Milliseconds 200
    $taskHealth = & $taskExe --state $taskState diagnose 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Output $taskHealth; return }
    if ($taskProcess.HasExited) { throw 'Collector exited; check configuration and port.' }
}
throw 'Collector did not become ready.'
