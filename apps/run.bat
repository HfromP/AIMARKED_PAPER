@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "CONFIG_FILE=%SCRIPT_DIR%\system.config"

echo ==============================
echo   Millestone 서버 시작
echo ==============================

:: system.config에서 로컬 Python 경로 읽기
set "PYTHON_BIN="
if exist "%CONFIG_FILE%" (
    for /f "tokens=1,* delims==" %%A in ('findstr /B "PYTHON_BIN=" "%CONFIG_FILE%"') do set "PYTHON_BIN=%%B"
)

:: 로컬 Python 없으면 시스템 Python으로 폴백
if "!PYTHON_BIN!"=="" goto :use_system_python
if not exist "!PYTHON_BIN!" goto :use_system_python
goto :start_server

:use_system_python
for /f "tokens=*" %%P in ('where python 2^>nul') do (
    set "PYTHON_BIN=%%P"
    goto :system_python_found
)
echo [오류] Python을 찾을 수 없습니다. Python 3를 설치해주세요.
pause
exit /b 1

:system_python_found
:: Windows Store 파이썬 스텁 감지 — 스텁은 --version 실행 시 errorlevel 9009 반환
"!PYTHON_BIN!" --version >nul 2>nul
if errorlevel 1 (
    echo [오류] Python이 제대로 설치되어 있지 않습니다.
    echo        python.org 에서 Python 3 를 설치하거나,
    echo        Installations\install_python.bat 를 실행하여 로컬 Python 을 설치해주세요.
    pause
    exit /b 1
)
echo [안내] 로컬 Python 환경이 없습니다. 시스템 Python으로 서버를 시작합니다.
echo        브라우저에서 온보딩 화면을 통해 환경을 설치해주세요.
echo.

:start_server

set "SERVER_PY=%SCRIPT_DIR%\server.py"

if not exist "%SERVER_PY%" (
    echo [오류] server.py 파일을 찾을 수 없습니다: %SERVER_PY%
    pause
    exit /b 1
)

echo Python : !PYTHON_BIN!
echo 서버   : %SERVER_PY%
echo.
echo 서버 주소: http://localhost:5500/main.html
echo 종료하려면 Ctrl+C 를 누르세요.
echo ==============================
echo.

"!PYTHON_BIN!" "%SERVER_PY%"
set "SERVER_EXIT=%errorlevel%"
if %SERVER_EXIT% neq 0 (
    echo.
    echo [오류] 서버가 비정상 종료되었습니다. ^(종료 코드: %SERVER_EXIT%^)
    echo        위의 오류 메시지를 확인하세요.
)
echo.
echo 서버가 종료되었습니다. 창을 닫으려면 아무 키나 누르세요.
pause >nul
