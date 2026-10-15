param([string]$State, [string]$Output, [ValidateSet('http','bridge')][string]$Transport = 'http')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskExe = Join-Path $taskRoot 'codex-usage-collector.exe'
if (-not (Test-Path -LiteralPath $taskExe)) { $taskExe = Join-Path $taskRoot 'dist\codex-usage-collector.exe' }
if (-not $State) { $State = Join-Path (Split-Path $taskExe -Parent) '.runtime' }
if (-not $Output) { $Output = Join-Path (Split-Path $taskExe -Parent) 'paired\codex-usage-status.js' }
& $taskExe --state $State pair --transport $Transport --output $Output
if ($LASTEXITCODE -ne 0) { throw 'Pairing failed.' }
Write-Output 'Private paired script is ready. Import it into Codex++ after verifying the communication route.'
