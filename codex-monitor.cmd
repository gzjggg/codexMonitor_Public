@echo off
pwsh.exe -NoLogo -NoProfile -File "%~dp0codex-monitor.ps1" %*
exit /b %errorlevel%
