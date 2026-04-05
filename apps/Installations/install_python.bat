@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

:: 경로 설정
:: install_python.bat 위치: apps/Installations/
:: PYTHON_DIR → apps/dependencies/local_python
:: SERVER_DIR → apps/
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

pushd "%SCRIPT_DIR%\.." >nul
if errorlevel 1 (
    echo [오류] 서버 디렉터리로 이동할 수 없습니다: "%SCRIPT_DIR%\.."
    pause
    exit /b 1
)
set "SERVER_DIR=%CD%"
popd >nul
set "DEP_DIR=%SERVER_DIR%\dependencies"
set "PYTHON_DIR=%DEP_DIR%\local_python"
set "CONFIG_FILE=%SERVER_DIR%\system.config"

echo ==============================
echo   Python 로컬 설치 시작
echo ==============================
echo 설치 경로: %PYTHON_DIR%
echo.

:: 이미 설치되어 있으면 스킵
if exist "%PYTHON_DIR%\python.exe" (
    echo [이미 설치됨] %PYTHON_DIR%\python.exe
    (
        echo PYTHON_BIN=%PYTHON_DIR%\python.exe
        echo SERVER_DIR=%SERVER_DIR%
    ) > "%CONFIG_FILE%"
    echo.
    echo system.config 업데이트 완료: %CONFIG_FILE%
    echo.
    pause
    exit /b 0
)

echo [1/4] 최신 Python 버전 확인 중...

set "API_URL=https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
set "RELEASE_URL="

for /f "delims=" %%U in ('powershell -NoProfile -Command "$r = Invoke-RestMethod \"%API_URL%\"; $r.assets | Where-Object { $_.name -match 'cpython-3\.12' -and $_.name -match 'x86_64-pc-windows-msvc-install_only\.tar\.gz' } | Select-Object -First 1 -ExpandProperty browser_download_url"') do (
    set "RELEASE_URL=%%U"
)

if "!RELEASE_URL!"=="" (
    echo [오류] 다운로드 URL을 찾을 수 없습니다. 네트워크 연결을 확인하세요.
    pause
    exit /b 1
)

echo   -^> !RELEASE_URL!
echo.

echo [2/4] 다운로드 중...
set "TMPFILE=%TEMP%\python_build_standalone.tar.gz"
curl -L -o "!TMPFILE!" "!RELEASE_URL!"
if errorlevel 1 (
    echo [오류] 다운로드 실패
    pause
    exit /b 1
)
echo.

echo [3/4] 압축 해제 중...
set "TAR_CMD="
where tar >nul 2>&1
if not errorlevel 1 set "TAR_CMD=tar"
if "!TAR_CMD!"=="" (
    where bsdtar >nul 2>&1
    if not errorlevel 1 set "TAR_CMD=bsdtar"
)
if "!TAR_CMD!"=="" (
    echo [오류] tar 명령을 PATH에서 찾을 수 없습니다.
    echo        다음 중 하나를 확인해 주세요:
    echo        - Windows 내장 tar 사용 가능 여부 확인 ^(Windows 10 1903 이상^)
    echo        - Git for Windows 또는 WSL 설치
    echo        - tar/bsdtar 별도 설치 후 PATH 등록
    del "!TMPFILE!" 2>nul
    pause
    exit /b 1
)
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
"!TAR_CMD!" -xzf "!TMPFILE!" -C "%PYTHON_DIR%" --strip-components=1
if errorlevel 1 (
    echo [오류] 압축 해제 실패. 다운로드 파일이 손상되었을 수 있습니다.
    del "!TMPFILE!" 2>nul
    pause
    exit /b 1
)
del "!TMPFILE!" 2>nul

if not exist "%PYTHON_DIR%\python.exe" (
    echo [오류] Python 실행 파일을 찾을 수 없습니다.
    pause
    exit /b 1
)

echo   -^> Python 설치 위치: %PYTHON_DIR%\python.exe
echo.

echo [4/4] system.config 생성 중...
(
    echo PYTHON_BIN=%PYTHON_DIR%\python.exe
    echo SERVER_DIR=%SERVER_DIR%
) > "%CONFIG_FILE%"
echo   -^> %CONFIG_FILE% 생성 완료
echo.

echo ==============================
"%PYTHON_DIR%\python.exe" --version
echo 설치 완료!
echo ==============================
echo.
echo 이제 run.bat 를 더블클릭해서 서버를 시작하세요.
echo.
pause
