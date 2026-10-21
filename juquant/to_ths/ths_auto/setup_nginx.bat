@echo off
setlocal EnableDelayedExpansion

rem ============================================================
rem  nginx reverse proxy + token auth - one-click installer
rem  Purpose: add a public entry + token auth for THSAutoTrader
rem  Flow: public -> nginx(:80, token check) -> THSAutoTrader(:5000, localhost only)
rem ============================================================

rem ---------- Config ----------
set "NGINX_VERSION=1.30.5"
set "INSTALL_DIR=C:\nginx"
set "LISTEN_PORT=80"
set "BACKEND_PORT=5000"
rem Leave empty to auto-generate a random token, or set a custom one
set "TOKEN="
rem ----------------------------

echo.
echo ============================================
echo   nginx reverse proxy + token auth installer
echo ============================================
echo   Version    : %NGINX_VERSION%
echo   Install dir: %INSTALL_DIR%
echo   Listen port: %LISTEN_PORT%
echo   Backend    : %BACKEND_PORT% (THSAutoTrader)
echo ============================================
echo.

rem ---------- 0. Check admin ----------
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please run this script as Administrator.
    pause
    exit /b 1
)

rem ---------- 1. Generate token ----------
if "%TOKEN%"=="" (
    echo [INFO] No token specified, generating a random token...
    set "CHARSET=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    set "TOKEN="
    for /l %%i in (1,1,32) do (
        set /a "_rand=!random! %% 62"
        for %%c in (!_rand!) do set "TOKEN=!TOKEN!!CHARSET:~%%c,1!"
    )
    echo [INFO] Generated token: !TOKEN!
) else (
    echo [INFO] Using custom token: %TOKEN%
)

rem ---------- 2. Download nginx ----------
set "ZIP=%TEMP%\nginx-%NGINX_VERSION%.zip"
set "URL=https://nginx.org/download/nginx-%NGINX_VERSION%.zip"

if exist "%INSTALL_DIR%\nginx.exe" (
    echo [INFO] nginx already installed, skipping download and extract.
    goto :config
)

echo [INFO] Downloading nginx %NGINX_VERSION% ...
echo         %URL%
powershell -NoProfile -Command ^
    "$ProgressPreference='SilentlyContinue';" ^
    "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
    "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing"

if not exist "%ZIP%" (
    echo [ERROR] Download failed. Please check your network.
    pause
    exit /b 1
)
echo [INFO] Download complete: %ZIP%

rem ---------- 3. Extract ----------
echo [INFO] Extracting to %INSTALL_DIR% ...
powershell -NoProfile -Command ^
    "if (Test-Path '%INSTALL_DIR%') { Remove-Item '%INSTALL_DIR%' -Recurse -Force };" ^
    "Expand-Archive -Path '%ZIP%' -DestinationPath 'C:\' -Force;" ^
    "Move-Item 'C:\nginx-%NGINX_VERSION%' '%INSTALL_DIR%' -Force"
if not exist "%INSTALL_DIR%\nginx.exe" (
    echo [ERROR] Extraction failed.
    pause
    exit /b 1
)
echo [INFO] Extraction complete.

:config
rem ---------- 4. Write nginx.conf via PowerShell ----------
echo [INFO] Writing nginx config with token auth...

set "CONF=%INSTALL_DIR%\conf\nginx.conf"
set "LPORT=%LISTEN_PORT%"
set "BPORT=%BACKEND_PORT%"

powershell -NoProfile -Command ^
    "$tok = '%TOKEN%';" ^
    "$lines = @(" ^
    "'# nginx reverse proxy for THSAutoTrader with token auth'," ^
    "'worker_processes  1;'," ^
    "''," ^
    "'events {'," ^
    "'    worker_connections  1024;'," ^
    "'}'," ^
    "''," ^
    "'http {'," ^
    "'    include       mime.types;'," ^
    "'    default_type  application/octet-stream;'," ^
    "'    sendfile        on;'," ^
    "'    keepalive_timeout  65;'," ^
    "''," ^
    "'    access_log  logs/access.log;'," ^
    "'    error_log   logs/error.log;'," ^
    "''," ^
    "'    server {'," ^
    "'        listen       %LPORT%;'," ^
    "'        server_name  _;'," ^
    "''," ^
    "'        # expected token, must match THSClient token param'," ^
    "('        set $expected_token ' + $tok + ';')," ^
    "''," ^
    "'        # health check is public'," ^
    "'        location = /health {'," ^
    "'            proxy_pass http://127.0.0.1:%BPORT%;'," ^
    "'        }'," ^
    "''," ^
    "'        location / {'," ^
    "'            # token check via X-Auth-Token header'," ^
    "'            if ($http_x_auth_token != $expected_token) {'," ^
    "'                return 401 unauthorized;'," ^
    "'            }'," ^
    "'            proxy_pass http://127.0.0.1:%BPORT%;'," ^
    "'            proxy_set_header Host $host;'," ^
    "'            proxy_set_header X-Real-IP $remote_addr;'," ^
    "'            proxy_read_timeout  60s;'," ^
    "'            proxy_send_timeout  60s;'," ^
    "'        }'," ^
    "'    }'," ^
    "'}'" ^
    ");" ^
    "[System.IO.File]::WriteAllText('%CONF%', ($lines -join [Environment]::NewLine))"

if not exist "%CONF%" (
    echo [ERROR] Failed to write nginx config.
    pause
    exit /b 1
)
echo [INFO] Config written to: %CONF%

rem ---------- 5. Save token ----------
echo [INFO] Saving token to %INSTALL_DIR%\token.txt
> "%INSTALL_DIR%\token.txt" echo %TOKEN%

rem ---------- 5b. Ensure logs dir exists ----------
if not exist "%INSTALL_DIR%\logs" mkdir "%INSTALL_DIR%\logs"

rem ---------- 6. Test config ----------
echo [INFO] Validating nginx config syntax...
"%INSTALL_DIR%\nginx.exe" -p "%INSTALL_DIR%" -t
if %errorlevel% neq 0 (
    echo [ERROR] nginx config validation failed, see output above.
    pause
    exit /b 1
)

rem ---------- 7. Start ----------
echo [INFO] Starting nginx...
"%INSTALL_DIR%\nginx.exe" -p "%INSTALL_DIR%"

rem ---------- 8. Verify ----------
echo [INFO] Waiting for nginx to be ready...
timeout /t 2 /nobreak >nul
echo [INFO] Local request WITHOUT token (expect 401):
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:%LISTEN_PORT%/balance' -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 'HTTP '+$_.Exception.Response.StatusCode.value__ }"
echo [INFO] Local request WITH token (expect 200 or JSON):
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:%LISTEN_PORT%/health' -Headers @{'X-Auth-Token'='%TOKEN%'} -UseBasicParsing -TimeoutSec 5; 'HTTP '+$r.StatusCode+'  '+$r.Content } catch { $_.Exception.Message }"

echo.
echo ============================================
echo   Installation complete!
echo ============================================
echo   nginx dir  : %INSTALL_DIR%
echo   Listen port: %LISTEN_PORT%
echo   Token      : %TOKEN%
echo   Token file : %INSTALL_DIR%\token.txt
echo.
echo   JoinQuant client example:
echo     THSClient("http://YOUR_ECS_PUBLIC_IP:%LISTEN_PORT%", token="%TOKEN%")
echo.
echo   IMPORTANT:
echo     1. Security group: open ONLY port %LISTEN_PORT% with IP whitelist,
echo        do NOT open backend port %BACKEND_PORT%.
echo     2. Make sure THSAutoTrader listens on 127.0.0.1:%BACKEND_PORT% only.
echo ============================================
echo.
pause
endlocal
