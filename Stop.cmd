@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Stop-Collector.ps1" %*
exit /b %errorlevel%
