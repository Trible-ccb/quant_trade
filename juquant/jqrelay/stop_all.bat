@echo off
chcp 65001 >nul
echo Stopping JQ Relay services...

:: Kill redis-server
taskkill /F /IM redis-server.exe 2>nul

:: Kill python processes running our scripts
for /f "tokens=2" %%a in ('tasklist /FI "WINDOWTITLE eq JQ Relay Service" /FO LIST 2^>nul ^| findstr PID') do (
    taskkill /F /PID %%a 2>nul
)

:: Kill by command line
wmic process where "CommandLine like '%%relay_bridge%%'" call terminate 2>nul
wmic process where "CommandLine like '%%redis_consumer%%'" call terminate 2>nul

echo All services stopped.