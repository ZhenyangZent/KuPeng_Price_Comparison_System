@echo off
setlocal
title Coupang Deal Hunter - Local Site Status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Status-CDH-Trial.ps1" %*
set "CDH_EXIT=%ERRORLEVEL%"
if "%~1"=="" (
  echo.
  pause
)
exit /b %CDH_EXIT%
