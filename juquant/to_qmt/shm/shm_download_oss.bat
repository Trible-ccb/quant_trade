@echo off
setlocal enabledelayedexpansion
title OSS File Downloader for SHM Bridge

:: ============================================
::  Configuration
:: ============================================
set "OSS_BASE_URL=https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com"
set "TARGET_DIR=C:\shm_qmt_bridge"
set "FILES=shm_external_redis_bridge.py shm_queue.py shm_start_bridge.bat shm_handle_orders.py"

:: ============================================
::  Create target directory
:: ============================================
if not exist "%TARGET_DIR%" (
    echo [INFO] Creating directory: %TARGET_DIR%
    mkdir "%TARGET_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create directory. Check permissions.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Directory already exists: %TARGET_DIR%
)

:: ============================================
::  Download each file
:: ============================================
echo.
echo ============================================
echo  Downloading files from OSS...
echo ============================================

set "FAILED=0"

for %%F in (%FILES%) do (
    echo.
    echo [DOWNLOAD] %%F ...
    curl -L -o "%TARGET_DIR%\%%F" "%OSS_BASE_URL%/%%F"
    
    if errorlevel 1 (
        echo [ERROR] Failed to download %%F
        set "FAILED=1"
    ) else (
        :: Verify file size > 0
        for %%A in ("%TARGET_DIR%\%%F") do (
            if %%~zA GTR 0 (
                echo [OK] %%F downloaded successfully ^(%%~zA bytes^)
            ) else (
                echo [ERROR] %%F is empty, download may have failed.
                set "FAILED=1"
            )
        )
    )
)

:: ============================================
::  Summary
:: ============================================
echo.
echo ============================================
if "%FAILED%"=="1" (
    echo [RESULT] Some files failed to download. Check errors above.
) else (
    echo [RESULT] All files downloaded to: %TARGET_DIR%
)
echo ============================================
pause