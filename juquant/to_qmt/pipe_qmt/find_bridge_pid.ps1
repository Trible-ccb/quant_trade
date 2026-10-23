$p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*external_redis_bridge.py*' } |
    Select-Object -First 1 -ExpandProperty ProcessId

if ($p) {
    Write-Output $p
    exit 0
} else {
    exit 1
}