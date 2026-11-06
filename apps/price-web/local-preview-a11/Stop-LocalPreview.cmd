@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Stop-LocalPreview.ps1" %*
exit /b %ERRORLEVEL%
