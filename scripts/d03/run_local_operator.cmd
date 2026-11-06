@echo off
setlocal
set "CDH_D03_ROOT=%~dp0..\.."
python "%CDH_D03_ROOT%\scripts\d03\local_operator.py" %*
exit /b %errorlevel%
