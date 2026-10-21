# ============================================================
#  SHM Redis Bridge Auto Deploy Script
#  Downloads files from OSS, installs deps, starts manager.bat
# ============================================================

# ---------- Configuration ----------
$TargetDir = "C:\redis_pipe_qmt"
$OssBase   = "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/pipe"

$Files = @(
    @{ Url = "$OssBase/manager.bat";                Name = "manager.bat" },
    @{ Url = "$OssBase/external_redis_bridge.py";   Name = "external_redis_bridge.py" },
    @{ Url = "$OssBase/_run_bridge.bat";            Name = "_run_bridge.bat" },
    @{ Url = "$OssBase/find_bridge_pid.ps1";         Name = "find_bridge_pid.ps1" }
)

# ---------- Step 1: Ensure target directory ----------
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Step 1: Prepare target directory" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
    Write-Host "[OK] Created directory: $TargetDir" -ForegroundColor Green
} else {
    Write-Host "[OK] Directory exists: $TargetDir" -ForegroundColor Green
}

# ---------- Step 2: Download files from OSS ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Step 2: Download files from OSS" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

foreach ($f in $Files) {
    $dest = Join-Path $TargetDir $f.Name
    Write-Host "[DOWNLOAD] $($f.Url)"
    Write-Host "        -> $dest"

    try {
        # Use TLS 1.2 for HTTPS
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $f.Url -OutFile $dest -UseBasicParsing -TimeoutSec 30

        if (Test-Path $dest) {
            $size = (Get-Item $dest).Length
            if ($size -gt 0) {
                Write-Host "[OK] Downloaded $($f.Name) ($size bytes)" -ForegroundColor Green
            } else {
                Write-Host "[ERROR] $($f.Name) is empty (0 bytes)" -ForegroundColor Red
                exit 1
            }
        }
    } catch {
        Write-Host "[ERROR] Download failed: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
}

# ---------- Step 3: Check Python ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Step 3: Verify Python environment" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "[ERROR] python not found in PATH." -ForegroundColor Red
    Write-Host "        Install Python 3.8+ and add to PATH."
    exit 1
}

Write-Host "[OK] Python found: $($pythonCmd.Source)" -ForegroundColor Green
python --version

# ---------- Step 4: Install dependencies ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Step 4: Install Python dependencies" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

Write-Host "[PIP] Installing redis and pywin32 ..."
python -m pip install --upgrade pip --quiet

python -m pip install redis pywin32
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed (exit code $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "        Try running manually: python -m pip install redis pywin32"
    exit 1
}
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# ---------- Step 5: Start bridge via manager.bat ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Step 5: Start bridge service" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

Set-Location $TargetDir

if (-not (Test-Path (Join-Path $TargetDir "manager.bat"))) {
    Write-Host "[ERROR] manager.bat not found in $TargetDir" -ForegroundColor Red
    exit 1
}

Write-Host "[START] Launching: manager.bat start"
cmd /c "manager.bat start"

# Give the process a moment to launch
Start-Sleep -Seconds 2

# ---------- Step 6: Verify ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host " Step 6: Verify" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

$bridgeProc = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*external_redis_bridge.py*' } |
    Select-Object -First 1

if ($bridgeProc) {
    Write-Host "[OK] Bridge is running. PID = $($bridgeProc.ProcessId)" -ForegroundColor Green
} else {
    Write-Host "[WARN] Bridge process not detected yet." -ForegroundColor Yellow
    Write-Host "       It may still be starting. Check log:"
    Write-Host "       $TargetDir\external_redis_bridge.log"
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Deployment complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Directory : $TargetDir"
Write-Host "Log file  : $TargetDir\external_redis_bridge.log"
Write-Host ""
Write-Host "Management commands:"
Write-Host "  cd $TargetDir"
Write-Host "  manager.bat start   - Start bridge"
Write-Host "  manager.bat stop    - Stop bridge"
Write-Host "  manager.bat status  - Show status"
Write-Host "  manager.bat log     - View log"
Write-Host ""