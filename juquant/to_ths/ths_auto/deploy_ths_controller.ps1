<#
.SYNOPSIS
    THSAutoTrader Deployment Script
.DESCRIPTION
    Runs on Aliyun ECS Windows Server. Automatically:
      1. Creates C:\ths_controller directory
      2. Downloads ths_auto_trader_dist.zip and extracts it into that directory
      3. Downloads setup_nginx.bat into that directory
      4. Downloads gen_config.ps1 into that directory
      5. Executes setup_nginx.bat to install and start the Nginx service
.NOTES
    Must be run as Administrator.
#>

# ==================== Admin privilege check ====================
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentPrincipal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)) {
    Write-Host "[ERROR] Please run this script as Administrator!" -ForegroundColor Red
    Write-Host "Right-click PowerShell -> Run as administrator" -ForegroundColor Yellow
    pause
    exit 1
}

# ==================== Variables ====================
$TargetDir   = "C:\ths_controller"
$DistUrl     = "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/ths_auto_trader_dist.zip"
$BatUrl      = "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/setup_nginx.bat"
$CloseUrl      = "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/close_ecs.bat"
$GenCfgUrl   = "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/gen_config.ps1"
$MngNginxUrl   = "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/manage_nginx.bat"
$DistZip     = Join-Path $TargetDir "ths_auto_trader_dist.zip"
$BatFile     = Join-Path $TargetDir "setup_nginx.bat"
$CloseFile     = Join-Path $TargetDir "close_ecs.bat"
$GenCfgFile  = Join-Path $TargetDir "gen_config.ps1"
$MngNginxFile  = Join-Path $TargetDir "manage_nginx.bat"

# ==================== Step 1: Create target directory ====================
Write-Host "`n[1/5] Checking and creating directory: $TargetDir" -ForegroundColor Cyan
if (-not (Test-Path -Path $TargetDir)) {
    try {
        New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
        Write-Host "  Directory created successfully" -ForegroundColor Green
    }
    catch {
        Write-Host "  Failed to create directory: $_" -ForegroundColor Red
        pause
        exit 1
    }
}
else {
    Write-Host "  Directory already exists, skipping creation" -ForegroundColor Yellow
}

# ==================== Step 2: Download ths_auto_trader_dist.zip ====================
Write-Host "`n[2/5] Downloading ths_auto_trader_dist.zip ..." -ForegroundColor Cyan
if (Test-Path -Path $DistZip) {
    Remove-Item -Path $DistZip -Force
    Write-Host "  Removed old ths_auto_trader_dist.zip" -ForegroundColor Yellow
}
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $DistUrl -OutFile $DistZip -UseBasicParsing -ErrorAction Stop
    $fileSize = [math]::Round((Get-Item $DistZip).Length / 1MB, 2)
    Write-Host "  Download completed, file size: $fileSize MB" -ForegroundColor Green
}
catch {
    Write-Host "  Download failed: $_" -ForegroundColor Red
    pause
    exit 1
}

# ==================== Step 3: Extract ths_auto_trader_dist.zip ====================
Write-Host "`n[3/5] Extracting ths_auto_trader_dist.zip to $TargetDir ..." -ForegroundColor Cyan
try {
    Expand-Archive -Path $DistZip -DestinationPath $TargetDir -Force -ErrorAction Stop
    Write-Host "  Extraction completed" -ForegroundColor Green
}
catch {
    Write-Host "  Extraction failed: $_" -ForegroundColor Red
    pause
    exit 1
}

# Cleanup zip file after extraction
Remove-Item -Path $DistZip -Force
Write-Host "  Cleaned up ths_auto_trader_dist.zip" -ForegroundColor Gray

# ==================== Step 4: Download setup_nginx.bat and gen_config.ps1 ====================
Write-Host "`n[4/5] Downloading setup_nginx.bat and gen_config.ps1 ..." -ForegroundColor Cyan

# 4.1 Download setup_nginx.bat
if (Test-Path -Path $BatFile) {
    Remove-Item -Path $BatFile -Force
    Write-Host "  Removed old setup_nginx.bat" -ForegroundColor Yellow
}
try {
    Invoke-WebRequest -Uri $BatUrl -OutFile $BatFile -UseBasicParsing -ErrorAction Stop
    Write-Host "  setup_nginx.bat downloaded successfully" -ForegroundColor Green
}
catch {
    Write-Host "  Failed to download setup_nginx.bat: $_" -ForegroundColor Red
    pause
    exit 1
}

# 4.1.1 Download close_ecs.bat
if (Test-Path -Path $CloseFile) {
    Remove-Item -Path $CloseFile -Force
    Write-Host "  Removed old close_ecs.bat" -ForegroundColor Yellow
}
try {
    Invoke-WebRequest -Uri $CloseUrl -OutFile $CloseFile -UseBasicParsing -ErrorAction Stop
    Write-Host "  close_ecs.bat downloaded successfully" -ForegroundColor Green
}
catch {
    Write-Host "  Failed to download close_ecs.bat: $_" -ForegroundColor Red
    pause
    exit 1
}

# 4.1.2 Download manage_nginx.bat
if (Test-Path -Path $MngNginxFile) {
    Remove-Item -Path $MngNginxFile -Force
    Write-Host "  Removed old manage_nginx.bat" -ForegroundColor Yellow
}
try {
    Invoke-WebRequest -Uri $MngNginxUrl -OutFile $MngNginxFile -UseBasicParsing -ErrorAction Stop
    Write-Host "  manage_nginx.bat downloaded successfully" -ForegroundColor Green
}
catch {
    Write-Host "  Failed to download manage_nginx.bat: $_" -ForegroundColor Red
    pause
    exit 1
}

# 4.2 Download gen_config.ps1
if (Test-Path -Path $GenCfgFile) {
    Remove-Item -Path $GenCfgFile -Force
    Write-Host "  Removed old gen_config.ps1" -ForegroundColor Yellow
}
try {
    Invoke-WebRequest -Uri $GenCfgUrl -OutFile $GenCfgFile -UseBasicParsing -ErrorAction Stop
    Write-Host "  gen_config.ps1 downloaded successfully" -ForegroundColor Green
}
catch {
    Write-Host "  Failed to download gen_config.ps1: $_" -ForegroundColor Red
    pause
    exit 1
}

# ==================== Step 5: Execute setup_nginx.bat ====================
Write-Host "`n[5/5] Executing setup_nginx.bat ..." -ForegroundColor Cyan
try {
    $process = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c `"$BatFile`"" `
        -WorkingDirectory $TargetDir `
        -Wait -PassThru -NoNewWindow

    if ($process.ExitCode -eq 0) {
        Write-Host "  setup_nginx.bat executed successfully" -ForegroundColor Green
    }
    else {
        Write-Host "  setup_nginx.bat returned exit code: $($process.ExitCode)" -ForegroundColor Yellow
        Write-Host "  Please check the bat output log for details" -ForegroundColor Yellow
    }
}
catch {
    Write-Host "  Failed to execute setup_nginx.bat: $_" -ForegroundColor Red
    pause
    exit 1
}

# ==================== Done ====================
Write-Host "`n========================================" -ForegroundColor Green
Write-Host " Deployment completed!" -ForegroundColor Green
Write-Host " Target directory: $TargetDir" -ForegroundColor Green
Write-Host " Files ready in target directory:" -ForegroundColor Green
Write-Host "   - setup_nginx.bat" -ForegroundColor Green
Write-Host "   - gen_config.ps1" -ForegroundColor Green
Write-Host " Nginx service installed and started via setup_nginx.bat" -ForegroundColor Green
Write-Host " Check Nginx status in the Services panel" -ForegroundColor Green
Write-Host "========================================`n" -ForegroundColor Green
pause