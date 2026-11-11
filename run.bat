@echo off
rem Match-3 launcher. Keep this file ASCII-only and CRLF: cmd.exe mangles
rem non-ASCII content after a codepage switch, and LF breaks goto labels.
setlocal
cd /d "%~dp0"

if not exist match3.py goto nofile

where py >nul 2>&1
if "%errorlevel%"=="0" goto run_py

where python >nul 2>&1
if "%errorlevel%"=="0" goto run_python

echo Python 3 not found.
echo Install it from https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during setup, then run this again.
pause
exit /b 1

:run_py
py -3 match3.py %*
goto finish

:run_python
python match3.py %*
goto finish

:finish
if not "%errorlevel%"=="0" pause
exit /b 0

:nofile
echo match3.py is missing in this folder:
echo   %cd%
pause
exit /b 1
