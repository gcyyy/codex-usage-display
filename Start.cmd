@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Start-Collector.ps1" %*
exit /b %errorlevel%
