@echo off
setlocal
title Coupang Deal Hunter - Windows Trial
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-CDH-Trial.ps1" %*
set "CDH_EXIT=%ERRORLEVEL%"
if "%~1"=="" (
  echo.
  echo Press any key to close this window. The local site keeps running until Stop-CDH-Trial.cmd is used.
  pause >nul
)
exit /b %CDH_EXIT%
