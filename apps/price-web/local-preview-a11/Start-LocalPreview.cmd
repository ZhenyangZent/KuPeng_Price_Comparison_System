@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-LocalPreview.ps1" %*
exit /b %ERRORLEVEL%
