@echo off
title Redis Installer

:: ============================================
:: Configuration - Modify as needed
:: ============================================
set REDIS_VERSION=Redis-x64-3.2.100
set REDIS_DOWNLOAD_URL=https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/Redis-x64-3.2.100.zip
set REDIS_PASSWORD=1A2B3C4D
set REDIS_PORT=6379
set SERVICE_NAME=Redis
:: ============================================

set SCRIPT_DIR=%~dp0
set REDIS_ZIP=%SCRIPT_DIR%%REDIS_VERSION%.zip
set REDIS_DIR=%SCRIPT_DIR%%REDIS_VERSION%

echo [INFO] Script directory: %SCRIPT_DIR%
echo.

:: Check for administrator privileges
net session >nul 2>nul
if errorlevel 1 goto :no_admin

:: -------------------------------------------------
:: Step 0: Check and remove existing service
:: -------------------------------------------------
echo [INFO] Checking for existing Redis service...
sc query "%SERVICE_NAME%" >nul 2>nul
if errorlevel 1 goto :no_service

echo [INFO] Found existing service "%SERVICE_NAME%". Removing it...
sc stop "%SERVICE_NAME%" >nul 2>nul
echo [INFO] Service stop command issued.
sc delete "%SERVICE_NAME%" >nul 2>nul
echo [INFO] Service delete command issued.
ping 127.0.0.1 -n 3 >nul
reg delete "HKLM\SYSTEM\CurrentControlSet\Services\%SERVICE_NAME%" /f >nul 2>nul
echo [INFO] Old service cleaned up.
goto :service_cleaned

:no_service
echo [INFO] No existing service found. Proceeding with fresh install.

:service_cleaned
echo.

:: -------------------------------------------------
:: Step 1: Download Redis (skip if exists)
:: -------------------------------------------------
if exist "%REDIS_ZIP%" goto :zip_exists
echo [INFO] Downloading Redis package...
echo [INFO] URL: %REDIS_DOWNLOAD_URL%
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%REDIS_DOWNLOAD_URL%' -OutFile '%REDIS_ZIP%'}"
if errorlevel 1 goto :download_fail
echo [INFO] Download completed: %REDIS_ZIP%
goto :extract

:zip_exists
echo [INFO] Installation package already exists: %REDIS_ZIP%

:: -------------------------------------------------
:: Step 2: Extract Redis (skip if already extracted)
:: -------------------------------------------------
:extract
if exist "%REDIS_DIR%" goto :extract_done
mkdir "%REDIS_DIR%"
echo [INFO] Extracting Redis...
powershell -Command "& {Expand-Archive -Path '%REDIS_ZIP%' -DestinationPath '%REDIS_DIR%' -Force}"
if errorlevel 1 goto :extract_fail
echo [INFO] Extraction completed: %REDIS_DIR%
goto :check_dir

:extract_done
echo [INFO] Redis directory already exists: %REDIS_DIR%

:check_dir
:: Verify the directory actually exists after extraction
if not exist "%REDIS_DIR%" (
    echo [ERROR] Redis directory not found after extraction!
    echo [HINT] Please check the ZIP content manually.
    pause
    exit /b 1
)
echo.

:: -------------------------------------------------
:: Step 3: Set Redis password and bind address in config files
:: -------------------------------------------------
cd "%REDIS_DIR%"
if errorlevel 1 (
    echo [ERROR] Failed to enter directory: %REDIS_DIR%
    pause
    exit /b 1
)

echo [INFO] Updating Redis configuration...
set CONFIG_FILE=redis.windows.conf
if not exist "%CONFIG_FILE%" goto :config_missing

:: Set password
powershell -Command "& {(Get-Content '%CONFIG_FILE%') -replace '^#?\s*requirepass\s+.*', 'requirepass %REDIS_PASSWORD%' | Set-Content '%CONFIG_FILE%'}"
findstr /C:"requirepass %REDIS_PASSWORD%" "%CONFIG_FILE%" >nul
if errorlevel 1 echo requirepass %REDIS_PASSWORD% >> "%CONFIG_FILE%"
echo [INFO] Redis password set to: %REDIS_PASSWORD%

:: Set bind address to 0.0.0.0
powershell -Command "& {(Get-Content '%CONFIG_FILE%') -replace '^#?\s*bind\s+.*', 'bind 0.0.0.0' | Set-Content '%CONFIG_FILE%'}"
:: Ensure the bind line actually exists; if not, append it
findstr /C:"bind 0.0.0.0" "%CONFIG_FILE%" >nul
if errorlevel 1 echo bind 0.0.0.0 >> "%CONFIG_FILE%"
echo [INFO] Bind address set to 0.0.0.0

:: Also update the service-specific config file
set SERVICE_CONFIG=redis.windows-service.conf
if exist "%SERVICE_CONFIG%" (
    powershell -Command "& {(Get-Content '%SERVICE_CONFIG%') -replace '^#?\s*requirepass\s+.*', 'requirepass %REDIS_PASSWORD%' | Set-Content '%SERVICE_CONFIG%'}"
    powershell -Command "& {(Get-Content '%SERVICE_CONFIG%') -replace '^#?\s*bind\s+.*', 'bind 0.0.0.0' | Set-Content '%SERVICE_CONFIG%'}"
    echo [INFO] Service config files updated.
)
goto :config_done

:config_missing
echo [WARN] Config file not found: %CONFIG_FILE%

:config_done
echo.

:: -------------------------------------------------
:: Step 4: Install and start service
:: -------------------------------------------------
echo [INFO] Installing Redis service...
redis-server.exe --service-install redis.windows.conf --service-name "%SERVICE_NAME%" --loglevel verbose
if errorlevel 1 goto :install_fail
echo [INFO] Redis service installed successfully.

echo [INFO] Starting Redis service...
redis-server.exe --service-start --service-name "%SERVICE_NAME%"
if errorlevel 1 goto :start_fail
echo [INFO] Redis service started successfully.

:: -------------------------------------------------
:: Success summary
:: -------------------------------------------------
echo.
echo ============================================
echo   Redis installation completed!
echo   Service name : %SERVICE_NAME%
echo   Port         : %REDIS_PORT%
echo   Password     : %REDIS_PASSWORD%
echo   Bind address : 0.0.0.0 (all interfaces)
echo   Install dir  : %REDIS_DIR%
echo ============================================
echo.
echo [HINT] Connect to Redis using:
echo   redis-cli.exe -h 127.0.0.1 -p %REDIS_PORT% -a %REDIS_PASSWORD%
echo.
echo [WARN] Binding to 0.0.0.0 exposes Redis to all network interfaces.
echo       Ensure your firewall and Redis security settings are appropriate.
echo.
pause
exit /b 0

:: Error handlers
:no_admin
echo [ERROR] This script must be run as Administrator!
echo [HINT] Right-click the script and select "Run as administrator"
pause
exit /b 1

:download_fail
echo [ERROR] Download failed. Please check your network.
pause
exit /b 1

:extract_fail
echo [ERROR] Extraction failed!
pause
exit /b 1

:install_fail
echo [ERROR] Service installation failed!
pause
exit /b 1

:start_fail
echo [ERROR] Service start failed!
pause
exit /b 1