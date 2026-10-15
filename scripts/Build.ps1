param([string]$PythonExe = 'python', [switch]$WithBridge)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Push-Location $taskRoot
$taskOldPythonPath = $env:PYTHONPATH
try {
    $taskBuildTools = Join-Path $taskRoot '.buildtools'
    $env:PYTHONPATH = $taskBuildTools
    & $PythonExe -m pip install --target $taskBuildTools -r requirements-build.lock
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
    & $PythonExe -m PyInstaller --noconfirm codex-usage-collector.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
    & $PythonExe -m scripts.exe_smoke
    if ($LASTEXITCODE -ne 0) { throw 'Executable smoke tests failed.' }
    if ($WithBridge) { & $PythonExe -m scripts.package_release --with-bridge }
    else { & $PythonExe -m scripts.package_release }
    if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
} finally {
    $env:PYTHONPATH = $taskOldPythonPath
    Pop-Location
}
