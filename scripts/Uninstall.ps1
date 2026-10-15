param([string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'Programs\CodexUsageStatus'))
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskExe = Join-Path $taskRoot 'codex-usage-collector.exe'
# Run outside the install directory so Windows can release and remove the owned EXE.
$taskTemporaryExe = Join-Path ([IO.Path]::GetTempPath()) ('codex-usage-uninstall-' + [Guid]::NewGuid().ToString('N') + '.exe')
try {
    Copy-Item -LiteralPath $taskExe -Destination $taskTemporaryExe
    & $taskTemporaryExe uninstall --install-dir $InstallDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Uninstall failed; data and backups are retained.' }
} finally {
    if (Test-Path -LiteralPath $taskTemporaryExe) { Remove-Item -LiteralPath $taskTemporaryExe }
}
