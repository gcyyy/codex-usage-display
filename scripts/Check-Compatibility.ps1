$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskExe = Join-Path $taskRoot 'codex-usage-collector.exe'
$taskReport = Join-Path $taskRoot '.runtime\compatibility-report.json'
$taskJson = & $taskExe --state (Join-Path $taskRoot '.runtime') compatibility-check --output $taskReport
$taskExit = $LASTEXITCODE
$taskResult = $taskJson | ConvertFrom-Json
Write-Output ('Compatibility: ' + $taskResult.status)
Write-Output ('Collector: ' + $taskResult.collectorVersion + ' / ' + $taskResult.collectorStatus)
Write-Output ('Codex++ bridge file: ' + $taskResult.host.status)
$taskResult.logFormats.versions | Format-Table version, records, supported
foreach ($taskIssue in $taskResult.issues) {
    Write-Output $taskIssue.message
    Write-Output $taskIssue.action
}
Write-Output ('Diagnostic report (no pairing tokens or conversation text): ' + $taskReport)
exit $taskExit
