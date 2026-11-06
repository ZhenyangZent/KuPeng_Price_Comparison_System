@echo off
setlocal
set "CDH_D02_ROOT=%~dp0..\.."
python "%CDH_D02_ROOT%\scripts\d02\d02_sync.py" %*
exit /b %errorlevel%
