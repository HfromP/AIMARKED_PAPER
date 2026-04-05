@echo off
chcp 65001 >/dev/null
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "CONFIG_FILE=%SCRIPT_DIR%\system.config"

echo ==============================
echo   Millestone Server Start
echo ==============================

:: Read local Python path from system.config
set "PYTHON_BIN="
if exist "%CONFIG_FILE%" (
    for /f "tokens=1,* delims==" %%A in ('findstr /B "PYTHON_BIN=" "%CONFIG_FILE%"') do set "PYTHON_BIN=%%B"
)

:: Fallback to system Python if local Python not found
if "!PYTHON_BIN!"=="" goto :use_system_python
if not exist "!PYTHON_BIN!" goto :use_system_python
goto :start_server

:use_system_python
for /f "tokens=*" %%P in ('where python 2^>nul') do (
    set "PYTHON_BIN=%%P"
    goto :system_python_found
)
echo [Error] Python not found. Please install Python 3.
pause
exit /b 1

:system_python_found
echo [Info] No local Python found. Using system Python.
echo        Please complete onboarding in the browser.
echo.

:start_server

set "SERVER_PY=%SCRIPT_DIR%\server.py"

if not exist "%SERVER_PY%" (
    echo [Error] server.py not found: %SERVER_PY%
    pause
    exit /b 1
)

echo Python : !PYTHON_BIN!
echo Server : %SERVER_PY%
echo.
echo URL    : http://localhost:5500/main.html
echo Press Ctrl+C to stop the server.
echo ==============================
echo.

"!PYTHON_BIN!" "%SERVER_PY%"
set "PYTHON_EXIT_CODE=%ERRORLEVEL%"
if not "%PYTHON_EXIT_CODE%"=="0" (
    echo.
    echo [Error] Server error occurred. Check the message above.
)
pause
exit /b %PYTHON_EXIT_CODE%
