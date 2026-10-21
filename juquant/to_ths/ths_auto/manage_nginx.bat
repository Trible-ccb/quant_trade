@echo off
setlocal EnableDelayedExpansion

rem ============================================================
rem  nginx manager: start / stop / reload / status
rem  Usage: manage_nginx.bat start | stop | reload | status
rem ============================================================

set "INSTALL_DIR=C:\nginx"
set "NGINX=%INSTALL_DIR%\nginx.exe"
set "PIDFILE=%INSTALL_DIR%\logs\nginx.pid"

if not exist "%NGINX%" (
    echo [ERROR] nginx not found. Run setup_nginx.bat first.
    exit /b 1
)

if "%~1"=="" (
    echo Usage: manage_nginx.bat start ^| stop ^| reload ^| status
    exit /b 1
)

if /i "%~1"=="start" (
    echo [INFO] Starting nginx...
    "%NGINX%" -p "%INSTALL_DIR%"
    exit /b 0
)

if /i "%~1"=="stop" (
    echo [INFO] Stopping nginx...
    "%NGINX%" -p "%INSTALL_DIR%" -s stop
    exit /b 0
)

if /i "%~1"=="reload" (
    echo [INFO] Reloading config (no downtime)...
    "%NGINX%" -p "%INSTALL_DIR%" -s reload
    exit /b 0
)

if /i "%~1"=="status" (
    if exist "%PIDFILE%" (
        set /p PID=<"%PIDFILE%"
        tasklist /fi "PID eq !PID!" | find /i "nginx" >nul
        if !errorlevel!==0 (
            echo [STATUS] nginx running, PID=!PID!
        ) else (
            echo [STATUS] nginx not running (pid file exists but process missing)
        )
    ) else (
        tasklist | find /i "nginx.exe" >nul
        if !errorlevel!==0 (
            echo [STATUS] nginx running (no pid file found)
        ) else (
            echo [STATUS] nginx not running
        )
    )
    exit /b 0
)

echo [ERROR] Unknown command: %~1
exit /b 1
