@echo off
setlocal
call "%~dp0apps\price-web\local-trial-a17\Status-CDH-Trial.cmd" %*
exit /b %ERRORLEVEL%
