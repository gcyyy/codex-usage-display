param([string]$State)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskExe = Join-Path $taskRoot 'codex-usage-collector.exe'
if (-not (Test-Path -LiteralPath $taskExe)) { $taskExe = Join-Path $taskRoot 'dist\codex-usage-collector.exe' }
if (-not $State) { $State = Join-Path (Split-Path $taskExe -Parent) '.runtime' }
& $taskExe --state $State stop
if ($LASTEXITCODE -ne 0) { throw 'Collector stop failed.' }
