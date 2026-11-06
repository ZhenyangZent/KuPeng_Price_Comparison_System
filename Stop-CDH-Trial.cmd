@echo off
setlocal
call "%~dp0apps\price-web\local-trial-a17\Stop-CDH-Trial.cmd" %*
exit /b %ERRORLEVEL%
