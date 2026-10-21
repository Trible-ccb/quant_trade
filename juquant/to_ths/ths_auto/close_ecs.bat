@echo off
chcp 65001 >nul
%1 mshta vbscript:CreateObject("Shell.Application").ShellExecute("cmd.exe","/c %~s0 ::","","runas",1)(window.close)&&exit
cd /d "%~dp0"
if "%~1"=="::" goto main

:main
echo ==============================================
echo          RDP Session Switch To Console Tool
echo WARNING: Current RDP connection will disconnect immediately after execution!
echo Please confirm your GUI program has been started!
echo ==============================================
echo Querying current session info...
for /f "tokens=2 delims= " %%a in ('query user ^| findstr "rdp-tcp"') do set SESSION_NAME=%%a

if "%SESSION_NAME%"=="" (
    echo RDP session not found!
    echo Please make sure you are logged in via RDP and try again.
    pause
    exit /b 1
)

echo Found session: %SESSION_NAME%
echo Ready to run command: tscon %SESSION_NAME% /dest:console
echo.
echo Execute after 1 seconds, press Ctrl+C to cancel
timeout /t 1 /nobreak >nul

tscon %SESSION_NAME% /dest:console
echo Command executed, RDP connection will close soon...
pause
