@echo off
title SHM Redis Bridge Launcher
cd /d %~dp0

echo ============================================
echo  Starting External Redis Bridge Process
echo  Shared Memory Name: QMT_SIGNAL_SHM
echo  Log File: shm_bridge.log
echo ============================================

:: Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

:: Check if redis library is installed
python -c "import redis" >nul 2>&1
if errorlevel 1 (
    echo [WARN] redis library not found. Installing...
    pip install redis
    if errorlevel 1 (
        echo [ERROR] Failed to install redis. Please run: pip install redis
        pause
        exit /b 1
    )
)

:: Force UTF-8 for Python stdout/stderr to avoid GBK encoding errors
set PYTHONIOENCODING=utf-8

:: Start the bridge process and redirect output to log file
python shm_external_redis_bridge.py >> shm_bridge.log 2>&1

echo.
echo Process exited. Check shm_bridge.log for details.
pause