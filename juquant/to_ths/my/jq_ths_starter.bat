@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ==================================================
REM  JoinQuant Redis Signal -^> EasyTHS -^> TongHuaShun
REM  One-click Deployment Script (First Run)
REM  After deployment, run.bat will be generated
REM ==================================================

REM ---------- User Config: edit only these two ----------
set "API_KEY=MySecretKey_ChangeMe_2024"
set "SCRIPT_URL=https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/redis_to_ths_server.py"
REM -----------------------------------------------------

set "BASE_DIR=C:\jq_ths_trader"
set "VENV_DIR=%BASE_DIR%\.venv"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"
set "PIP=%VENV_DIR%\Scripts\pip.exe"
set "EASYTHS=%VENV_DIR%\Scripts\easyths.exe"
set "CONFIG=%BASE_DIR%\config.toml"
set "SCRIPT_PATH=%BASE_DIR%\redis_to_ths_server.py"
set "RUN_BAT=%BASE_DIR%\run.bat"
set "HEALTH_URL=http://127.0.0.1:7648/api/v1/system/health"

title jq_ths_trader deployment

echo ==================================================
echo   JoinQuant Redis Signal -^> EasyTHS -^> TongHuaShun
echo   One-click Deployment Script
echo ==================================================
echo.

REM ---------- 1. Create directories ----------
echo [1/5] Creating directory %BASE_DIR% ...
if not exist "%BASE_DIR%" (
    mkdir "%BASE_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create directory. Check permissions.
        pause
        exit /b 1
    )
    echo       Directory created
) else (
    echo       Directory already exists
)
cd /d "%BASE_DIR%"

REM ---------- 2. Download redis_to_ths_server.py ----------
echo [2/5] Downloading redis_to_ths_server.py ...
if exist "%SCRIPT_PATH%" (
    echo       Already exists, skip download
    echo       Delete it manually and rerun to update
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
        "try { Invoke-WebRequest -Uri '%SCRIPT_URL%' -OutFile '%SCRIPT_PATH%' -UseBasicParsing; exit 0 } catch { Write-Host $_.Exception.Message; exit 1 }"
    if errorlevel 1 (
        echo [ERROR] Download failed. Check network or URL availability.
        pause
        exit /b 1
    )
    if not exist "%SCRIPT_PATH%" (
        echo [ERROR] File not found after download.
        pause
        exit /b 1
    )
    echo       Download completed
)

REM ---------- 3. Create Python virtual environment ----------
echo [3/5] Creating Python virtual environment ...
if not exist "%PYTHON%" (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] System Python not found. Install Python 3.12 and add to PATH.
        pause
        exit /b 1
    )
    python -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo       Virtual environment created
) else (
    echo       Virtual environment already exists
)

REM ---------- 4. Install dependencies ----------
echo [4/5] Installing dependencies (redis / httpx / easyths[server]) ...
if not exist "%EASYTHS%" (
    "%PYTHON%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [ERROR] Failed to upgrade pip.
        pause
        exit /b 1
    )
    "%PYTHON%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple redis httpx "easyths[server]"
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check network.
        pause
        exit /b 1
    )
    echo       Dependencies installed
) else (
    echo       Dependencies already available
)

REM ---------- 5. Generate run.bat ----------
echo [5/5] Generating standalone launcher run.bat ...
(
    echo @echo off
    echo chcp 65001 ^>nul
    echo setlocal
    echo.
    echo REM ==================================================
    echo REM  JoinQuant Redis Signal -^> EasyTHS -^> TongHuaShun
    echo REM  Double-click this file to start the service
    echo REM  Edit API_KEY below to change the key
    echo REM ==================================================
    echo.
    echo set "API_KEY=%API_KEY%"
    echo.
    echo set "BASE_DIR=%BASE_DIR%"
    echo set "PYTHON=%PYTHON%"
    echo set "EASYTHS=%EASYTHS%"
    echo set "CONFIG=%CONFIG%"
    echo set "SCRIPT=%SCRIPT_PATH%"
    echo set "HEALTH_URL=%HEALTH_URL%"
    echo.
    echo cd /d "%BASE_DIR%"
    echo.
    echo if not exist "%PYTHON%" ^(
    echo     echo [ERROR] Virtual environment missing. Run start.bat first.
    echo     pause
    echo     exit /b 1
    echo ^)
    echo.
    echo echo [1/3] Writing EasyTHS config file...
    echo ^(
    echo     echo [app]
    echo     echo onnx_model_dir = ""
    echo     echo save_error_captcha_image = true
    echo     echo.
    echo     echo [trading]
    echo     echo app_path = "C:/THS_Link/xiadan.exe"
    echo     echo.
    echo     echo [queue]
    echo     echo max_size = 1000
    echo     echo operation_timeout = 10.0
    echo     echo.
    echo     echo [api]
    echo     echo host = "127.0.0.1"
    echo     echo port = 7648
    echo     echo rate_limit = 100
    echo     echo cors_origins = "*"
    echo     echo key = "%%API_KEY%%"
    echo     echo ip_whitelist = ""
    echo     echo.
    echo     echo [logging]
    echo     echo level = "INFO"
    echo     echo file = ""
    echo ^) ^> "%CONFIG%"
    echo.
    echo set "PROBE=import httpx,sys; sys.exit^(0 if httpx.get^('%HEALTH_URL%',headers={'Authorization':'Bearer %%API_KEY%%'},timeout=2^).status_code==200 else 1^)"
    echo.
    echo "%PYTHON%" -c "%%PROBE%%" ^>nul 2^>^&1
    echo if not errorlevel 1 ^(
    echo     echo [2/3] EasyTHS server already running
    echo     goto :easyths_ready
    echo ^)
    echo.
    echo echo [2/3] Starting EasyTHS server...
    echo start "EasyTHS Server" cmd /k "%EASYTHS%" --config "%CONFIG%"
    echo.
    echo echo       Waiting for EasyTHS to be ready...
    echo set /a tries=0
    echo :wait_easyths
    echo timeout /t 2 /nobreak ^>nul
    echo "%PYTHON%" -c "%%PROBE%%" ^>nul 2^>^&1
    echo if not errorlevel 1 goto :easyths_ready
    echo set /a tries+=1
    echo if %%tries%% lss 15 goto wait_easyths
    echo echo       [WARN] EasyTHS not ready within 30s, continuing anyway
    echo.
    echo :easyths_ready
    echo.
    echo set "EASYTHS_API_KEY=%%API_KEY%%"
    echo.
    echo echo [3/3] Starting Redis consumer service...
    echo echo --------------------------------------------------
    echo echo.
    echo "%PYTHON%" "%SCRIPT_PATH%"
    echo.
    echo echo.
    echo echo Consumer service exited.
    echo pause
) > "%RUN_BAT%"

if not exist "%RUN_BAT%" (
    echo [ERROR] Failed to generate run.bat
    pause
    exit /b 1
)
echo       run.bat generated: %RUN_BAT%

echo.
echo ==================================================
echo   Deployment complete. Starting service...
echo   Double-click %RUN_BAT% to start next time.
echo ==================================================
echo.

REM ---------- Launch immediately ----------
call "%RUN_BAT%"