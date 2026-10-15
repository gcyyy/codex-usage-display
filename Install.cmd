@echo off
setlocal
"%~dp0codex-usage-collector.exe" install --package-root "%~dp0." --install-bridge %*
set "result=%errorlevel%"
if not "%result%"=="0" echo Installation failed. Keep this window to read the message above.
if not defined CODEX_USAGE_UNATTENDED pause
exit /b %result%
