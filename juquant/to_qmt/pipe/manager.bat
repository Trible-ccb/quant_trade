@echo off
setlocal enabledelayedexpansion
title Redis Bridge Manager
cd /d "%~dp0"

set "SCRIPT_NAME=external_redis_bridge.py"
set "LOG_FILE=%~dp0external_redis_bridge.log"
set "RUNNER=%~dp0_run_bridge.bat"
set "ARG1=%~1"

if /i "%ARG1%"=="start"   goto do_start
if /i "%ARG1%"=="stop"    goto do_stop
if /i "%ARG1%"=="restart" goto do_restart
if /i "%ARG1%"=="status"  goto do_status
if /i "%ARG1%"=="log"     goto view_log
if "%ARG1%"==""           goto menu
goto usage

:menu
cls
echo ============================================
echo  Redis Bridge Manager
echo ============================================
echo.
echo   [1] Start bridge
echo   [2] Stop bridge
echo   [3] Restart bridge
echo   [4] Show status
echo   [5] View log (last 30 lines)
echo   [6] Exit
echo.
set /p "CHOICE=Enter choice [1-6]: "
if "%CHOICE%"=="1" goto do_start
if "%CHOICE%"=="2" goto do_stop
if "%CHOICE%"=="3" goto do_restart
if "%CHOICE%"=="4" goto do_status
if "%CHOICE%"=="5" goto view_log
if "%CHOICE%"=="6" goto end
goto menu

:find_pid
set "FOUND_PID="
for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find_bridge_pid.ps1" 2^>nul`) do set "FOUND_PID=%%P"
if defined FOUND_PID set "FOUND_PID=!FOUND_PID: =!"
goto :eof

:do_start
call :find_pid
if defined FOUND_PID (
    echo [INFO] Bridge already running. PID=!FOUND_PID!
    goto end
)
if not exist "%SCRIPT_NAME%" (
    echo [ERROR] %SCRIPT_NAME% not found in %~dp0
    goto end
)
if not exist "%RUNNER%" (
    echo [ERROR] _run_bridge.bat not found in %~dp0
    goto end
)
echo [INFO] Starting bridge: %SCRIPT_NAME%
start "Redis_Bridge_Worker" /min "%RUNNER%"
set "WAIT=0"
:wait_loop
timeout /t 1 /nobreak >nul
call :find_pid
if defined FOUND_PID goto start_ok
set /a WAIT+=1
if !WAIT! LSS 8 goto wait_loop
echo [ERROR] Failed to start after 8 seconds. Check log: %LOG_FILE%
goto end
:start_ok
echo [OK] Bridge started. PID=!FOUND_PID!
goto end

:do_stop
call :find_pid
if not defined FOUND_PID (
    echo [INFO] No running bridge found.
    goto end
)
echo [INFO] Stopping PID=!FOUND_PID!
taskkill /F /PID !FOUND_PID! >nul 2>&1
timeout /t 1 /nobreak >nul
call :find_pid
if defined FOUND_PID (
    echo [ERROR] Process still alive. PID=!FOUND_PID!
) else (
    echo [OK] Bridge stopped.
)
goto end

:do_restart
echo [INFO] Restarting...
call :do_stop
call :do_start
goto end

:do_status
call :find_pid
echo ============================================
echo  Bridge Status
echo ============================================
if defined FOUND_PID (
    echo   State : RUNNING
    echo   PID   : !FOUND_PID!
) else (
    echo   State : STOPPED
)
if exist "%LOG_FILE%" (
    for %%A in ("%LOG_FILE%") do echo   Log   : %%~fA  ^(%%~zA bytes^)
) else (
    echo   Log   : not created yet
)
echo ============================================
goto end

:view_log
if not exist "%LOG_FILE%" (
    echo [INFO] No log file yet.
    goto end
)
powershell -NoProfile -Command "Get-Content -Path '%LOG_FILE%' -Tail 30"
goto end

:usage
echo Usage: %~nx0 [start^|stop^|restart^|status^|log]
exit /b 1

:end
echo.
if "%ARG1%"=="" (
    pause
    goto menu
)
exit /b 0