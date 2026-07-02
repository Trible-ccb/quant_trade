@echo off
chcp 65001 >nul
title Auto Setup for JoinQuant-MiniQMT

:: ===== Config =====
set "PROJECT_DIR=C:\qmt_trade"
set "PYTHON_VERSION=3.12.10"
set "PYTHON_INSTALLER=%TEMP%\python-%PYTHON_VERSION%-amd64.exe"
set "PYTHON_URL=https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/python-3.12.10-amd64.exe"
set "QMT_DATA_DEFAULT=C:\QMT\userdata_mini"
set "SERVER_PORT=58620"
:: ===================

:: Check admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Not running as administrator. Firewall rule may fail.
)

echo ============================================================
echo  Auto Deploy for JoinQuant + MiniQMT
echo  Project: %PROJECT_DIR%
echo  Python : %PYTHON_VERSION%
echo  Port   : %SERVER_PORT%
echo ============================================================
echo.

:: ---------- 1. Python ----------
echo [1/6] Checking Python...
where python >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2 delims= " %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
    echo Found Python %PYTHON_VER%
    goto :PYTHON_OK
)

echo Downloading Python installer...
powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLER%'"
if not exist "%PYTHON_INSTALLER%" (
    echo Download failed. Check network.
    pause
    exit /b 1
)

echo Installing Python silently...
"%PYTHON_INSTALLER%" /quiet InstallAllUsers=1 PrependPath=1
if %errorlevel% neq 0 (
    echo Installation failed.
    pause
    exit /b 1
)
set "PATH=C:\Program Files\Python312\;C:\Program Files\Python312\Scripts\;%PATH%"
del "%PYTHON_INSTALLER%" 2>nul
echo Python installed.

:PYTHON_OK
echo.

:: ---------- 2. Project dir ----------
echo [2/6] Creating project directory...
if not exist "%PROJECT_DIR%" mkdir "%PROJECT_DIR%"
echo Dir: %PROJECT_DIR%
echo.

:: ---------- 3. Virtual env ----------
echo [3/6] Creating virtual environment...
if exist "%PROJECT_DIR%\.venv" (
    echo .venv already exists, skip.
) else (
    python -m venv "%PROJECT_DIR%\.venv"
    if %errorlevel% neq 0 (
        echo Failed to create .venv.
        pause
        exit /b 1
    )
    echo .venv created.
)
echo.

:: ---------- 4. Install deps ----------
echo [4/6] Installing dependencies (bullet-trade)...
set "PIP_EXE=%PROJECT_DIR%\.venv\Scripts\pip.exe"
set "PYTHON_VENV=%PROJECT_DIR%\.venv\Scripts\python.exe"

"%PIP_EXE%" config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
"%PIP_EXE%" config set global.trusted-host pypi.tuna.tsinghua.edu.cn
"%PYTHON_VENV%" -m pip install --upgrade pip
"%PIP_EXE%" install "bullet-trade[qmt]"
if %errorlevel% neq 0 (
    echo Installation of bullet-trade failed.
    pause
    exit /b 1
)
echo Dependencies installed.
echo.

:: ---------- 5. .env file ----------
echo [5/6] Creating .env file...
set /p QMT_DATA="Enter QMT userdata path [default: %QMT_DATA_DEFAULT%]: "
if "%QMT_DATA%"=="" set "QMT_DATA=%QMT_DATA_DEFAULT%"

set /p ACCOUNT="Enter your securities account number: "
if "%ACCOUNT%"=="" (
    echo Account cannot be empty.
    pause
    exit /b 1
)

set /p TOKEN="Enter QMT_SERVER_TOKEN (leave blank to auto-generate): "
if "%TOKEN%"=="" (
    powershell -Command "$rand= -join ((48..57)+(65..90)+(97..122) | Get-Random -Count 8 | ForEach-Object {[char]$_}); Write-Output $rand" > %TEMP%\rand.txt
    set /p TOKEN=<%TEMP%\rand.txt
    del %TEMP%\rand.txt
    echo Auto-generated Token: %TOKEN%
)

(
echo QMT_DATA_PATH=%QMT_DATA%
echo QMT_ACCOUNT_ID=%ACCOUNT%
echo QMT_SERVER_TOKEN=%TOKEN%
) > "%PROJECT_DIR%\.env"

echo .env saved.
echo.

:: ---------- 6. Start script + firewall ----------
echo [6/6] Generating start script and firewall rule...

(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%PROJECT_DIR%"
echo call .venv\Scripts\activate
echo bullet-trade --env-file .env server --listen 0.0.0.0 --port %SERVER_PORT% --enable-data --enable-broker
echo pause
) > "%PROJECT_DIR%\start_server.bat"
echo start_server.bat generated.

netsh advfirewall firewall add rule name="QMT_Trade_%SERVER_PORT%" dir=in action=allow protocol=TCP localport=%SERVER_PORT% >nul 2>&1
if %errorlevel% equ 0 (
    echo Firewall port %SERVER_PORT% opened.
) else (
    echo [WARN] Failed to add firewall rule. Please open port manually.
)

echo.
echo ============================================================
echo  DEPLOYMENT COMPLETED!
echo ============================================================
echo.
echo Next steps:
echo 1. Make sure QMT client is logged in (standalone trading mode)
echo    and Python packages have been downloaded (first login needed).
echo 2. Run %PROJECT_DIR%\start_server.bat to start the service.
echo 3. In JoinQuant research, upload wrapper/helper and set HOST=public IP, TOKEN=%TOKEN%.
echo.
echo Manual start command:
echo   cd /d "%PROJECT_DIR%"
echo   .venv\Scripts\activate
echo   bullet-trade --env-file .env server --listen 0.0.0.0 --port %SERVER_PORT% --enable-data --enable-broker
echo.
pause