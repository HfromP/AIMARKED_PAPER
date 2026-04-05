@echo off
chcp 65001 >/dev/null
setlocal EnableDelayedExpansion

:: Path configuration
:: install_python.bat location: apps/Installations/
:: PYTHON_DIR -> apps/dependencies/local_python
:: SERVER_DIR -> apps/
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

pushd "%SCRIPT_DIR%\.." >/dev/null
if errorlevel 1 (
    echo [Error] Cannot navigate to server directory: "%SCRIPT_DIR%\.."
    pause
    exit /b 1
)
set "SERVER_DIR=%CD%"
popd >/dev/null
set "DEP_DIR=%SERVER_DIR%\dependencies"
set "PYTHON_DIR=%DEP_DIR%\local_python"
set "CONFIG_FILE=%SERVER_DIR%\system.config"

echo ==============================
echo   Python Local Install Start
echo ==============================
echo Install path: %PYTHON_DIR%
echo.

:: Skip if already installed
if exist "%PYTHON_DIR%\python.exe" (
    echo [Already installed] %PYTHON_DIR%\python.exe
    (
        echo PYTHON_BIN=%PYTHON_DIR%\python.exe
        echo SERVER_DIR=%SERVER_DIR%
    ) > "%CONFIG_FILE%"
    echo.
    echo system.config updated: %CONFIG_FILE%
    echo.
    pause
    exit /b 0
)

echo [1/4] Checking latest Python version...

set "API_URL=https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
set "RELEASE_URL="

for /f "delims=" %%U in ('powershell -NoProfile -Command "$r = Invoke-RestMethod \"%API_URL%\"; $r.assets | Where-Object { $_.name -match 'cpython-3\.12' -and $_.name -match 'x86_64-pc-windows-msvc-install_only\.tar\.gz' } | Select-Object -First 1 -ExpandProperty browser_download_url"') do (
    set "RELEASE_URL=%%U"
)

if "!RELEASE_URL!"=="" (
    echo [Error] Download URL not found. Check your network connection.
    pause
    exit /b 1
)

echo   -^> !RELEASE_URL!
echo.

echo [2/4] Downloading...
set "TMPFILE=%TEMP%\python_build_standalone.tar.gz"
curl -L -o "!TMPFILE!" "!RELEASE_URL!"
if errorlevel 1 (
    echo [Error] Download failed.
    pause
    exit /b 1
)
echo.

echo [3/4] Extracting...
set "TAR_CMD="
where tar >/dev/null 2>&1
if not errorlevel 1 set "TAR_CMD=tar"
if "!TAR_CMD!"=="" (
    where bsdtar >/dev/null 2>&1
    if not errorlevel 1 set "TAR_CMD=bsdtar"
)
if "!TAR_CMD!"=="" (
    echo [Error] tar command not found in PATH.
    echo        Please check one of the following:
    echo        - Check Windows built-in tar availability ^(Windows 10 1903 or later^)
    echo        - Install Git for Windows or WSL
    echo        - Install tar/bsdtar separately and add to PATH
    del "!TMPFILE!" 2>/dev/null
    pause
    exit /b 1
)
if not exist "%PYTHON_DIR%" mkdir "%PYTHON_DIR%"
"!TAR_CMD!" -xzf "!TMPFILE!" -C "%PYTHON_DIR%" --strip-components=1
if errorlevel 1 (
    echo [Error] Extraction failed. The downloaded file may be corrupted.
    del "!TMPFILE!" 2>/dev/null
    pause
    exit /b 1
)
del "!TMPFILE!" 2>/dev/null

if not exist "%PYTHON_DIR%\python.exe" (
    echo [Error] Python executable not found.
    pause
    exit /b 1
)

echo   -^> Python installed at: %PYTHON_DIR%\python.exe
echo.

echo [4/4] Creating system.config...
(
    echo PYTHON_BIN=%PYTHON_DIR%\python.exe
    echo SERVER_DIR=%SERVER_DIR%
) > "%CONFIG_FILE%"
echo   -^> %CONFIG_FILE% created
echo.

echo ==============================
"%PYTHON_DIR%\python.exe" --version
echo Install complete!
echo ==============================
echo.
echo Double-click run.bat to start the server.
echo.
pause
