@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Uninstall.ps1" %*
set "result=%errorlevel%"
if not defined CODEX_USAGE_UNATTENDED pause
exit /b %result%
