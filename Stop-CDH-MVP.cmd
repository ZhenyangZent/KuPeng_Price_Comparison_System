@echo off
setlocal
title Coupang Deal Hunter - Stop Local Site
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-mvp\Stop-CDH-MVP.ps1" %*
set "CDH_EXIT=%ERRORLEVEL%"
if "%~1"=="" (
  echo.
  pause
)
exit /b %CDH_EXIT%
