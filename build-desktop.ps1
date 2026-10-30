# CuReD Desktop Build Script (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File build-desktop.ps1
#
# Builds the BASE app (CuReD + Library): server/cured-server-base.spec into
# server/dist-base, which electron/package.json packages.
#
# Prerequisites:
#   - Node.js (with npm)
#   - A Python environment for the server build with server/requirements.txt,
#     PyInstaller and **CPU** torch (a CUDA torch adds ~3 GB and breaks GitHub's
#     2 GB release-file limit):
#       pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu
#     By default the conda environment "ben-base" is used (-PythonExe to override).

param(
    [switch]$SkipAngular,
    [switch]$SkipPython,
    [switch]$SkipElectron,
    [switch]$PackageOnly,  # Run 'electron-forge package' instead of 'make' (faster, no installer)
    [string]$PythonExe = "$env:USERPROFILE\miniconda3\envs\ben-base\python.exe"
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  BEn Desktop Build" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Build Angular ──────────────────────────────────────────────────────
if (-not $SkipAngular) {
    Write-Host "[1/3] Building Angular frontend (desktop config)..." -ForegroundColor Yellow
    Set-Location "$RootDir\app"

    $env:NODE_OPTIONS = "--openssl-legacy-provider"
    npx ng build --configuration=desktop

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Angular build failed!" -ForegroundColor Red
        exit 1
    }

    # Verify output exists
    if (-not (Test-Path "$RootDir\app\dist\uni-app\index.html")) {
        Write-Host "ERROR: Angular build output not found at app\dist\uni-app\" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Angular build complete." -ForegroundColor Green
} else {
    Write-Host "[1/3] Skipping Angular build." -ForegroundColor DarkGray
}

# ── Step 2: Build Python server ────────────────────────────────────────────────
if (-not $SkipPython) {
    Write-Host "[2/3] Building Python server (base) with PyInstaller..." -ForegroundColor Yellow
    Set-Location "$RootDir\server"

    if (-not (Test-Path $PythonExe)) {
        Write-Host "ERROR: Python for the server build not found: $PythonExe (use -PythonExe)" -ForegroundColor Red
        exit 1
    }

    # A CUDA torch would make the installer ~4 GB (GitHub rejects files over 2 GB)
    $torchVersion = & $PythonExe -c "import torch; print(torch.__version__)"
    if ($torchVersion -notmatch '\+cpu$') {
        Write-Host "ERROR: the build environment has torch $torchVersion; the base build needs the CPU build (+cpu)." -ForegroundColor Red
        exit 1
    }

    # Install PyInstaller if not present
    & $PythonExe -m pip show pyinstaller | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Installing PyInstaller..." -ForegroundColor DarkYellow
        & $PythonExe -m pip install pyinstaller
    }

    # Ultralytics would pip-install optional packages while PyInstaller analyses it
    $env:YOLO_AUTOINSTALL = "False"
    & $PythonExe -m PyInstaller cured-server-base.spec --noconfirm --distpath dist-base --workpath build-base

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: PyInstaller build failed!" -ForegroundColor Red
        exit 1
    }

    # Verify output exists (this is what electron/package.json packages)
    if (-not (Test-Path "$RootDir\server\dist-base\cured-server\cured-server.exe")) {
        Write-Host "ERROR: PyInstaller output not found at server\dist-base\cured-server\" -ForegroundColor Red
        exit 1
    }

    Write-Host "  Python server build complete." -ForegroundColor Green
} else {
    Write-Host "[2/3] Skipping Python build." -ForegroundColor DarkGray
}

# ── Step 3: Package Electron ───────────────────────────────────────────────────
Write-Host "[3/3] Packaging Electron app..." -ForegroundColor Yellow
Set-Location "$RootDir\electron"

# Install electron dependencies if needed
if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing Electron dependencies..." -ForegroundColor DarkYellow
    npm install
}

if ($PackageOnly -or $SkipElectron) {
    Write-Host "  Running electron-forge package (no installer)..." -ForegroundColor DarkYellow
    npx electron-forge package
} else {
    Write-Host "  Running electron-forge make (creating installer)..." -ForegroundColor DarkYellow
    npx electron-forge make
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Electron packaging failed!" -ForegroundColor Red
    exit 1
}

Write-Host "  Electron packaging complete." -ForegroundColor Green

# ── Done ───────────────────────────────────────────────────────────────────────
Set-Location $RootDir

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Build complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

if (-not $PackageOnly -and -not $SkipElectron) {
    $outDir = "$RootDir\electron\out\make"
    if (Test-Path $outDir) {
        Write-Host "Installer output:" -ForegroundColor White
        Get-ChildItem $outDir -Recurse -File | ForEach-Object { Write-Host "  $($_.FullName)" }
    }
} else {
    Write-Host "Packaged app: electron\out\ben-desktop-win32-x64\" -ForegroundColor White
}
