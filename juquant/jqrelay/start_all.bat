@echo off
chcp 65001 >nul
title JQ Relay Service
echo ==========================================
echo   JQ Relay Service - Starting...
echo ==========================================

cd /d C:\jqrelay

:: 1. Redis
if exist "redis\redis-server.exe" (
    echo [1/3] Starting Redis...
    start "" /b redis\redis-server.exe redis\redis.windows.conf
    timeout /t 2 /nobreak >nul
) else (
    echo [WARN] Redis not found
)

:: 2. Bridge
echo [2/3] Starting Relay Bridge...
start "" /b python relay_bridge.py

:: 3. Consumer
echo [3/3] Starting Stream Consumer...
start "" /b python redis_consumer.py

echo.
echo All services started.
pause