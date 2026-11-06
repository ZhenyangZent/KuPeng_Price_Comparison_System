@echo off
setlocal
title Coupang Deal Hunter - Local Price History
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-mvp\Start-CDH-MVP.ps1" %*
set "CDH_EXIT=%ERRORLEVEL%"
if "%~1"=="" (
  echo.
  echo Press any key to close this window. The local site keeps running until Stop-CDH-MVP.cmd is used.
  pause >nul
)
exit /b %CDH_EXIT%
