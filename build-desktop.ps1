# CuReD Desktop Build Script (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File build-desktop.ps1
#
# Prerequisites:
#   - Node.js (with npm)
#   - Python 3.8+ (with pip)
#   - PyInstaller: pip install pyinstaller
#
# Optional (for smaller build without GPU):
#   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

param(
    [switch]$SkipAngular,
    [switch]$SkipPython,
    [switch]$SkipElectron,
    [switch]$PackageOnly  # Run 'electron-forge package' instead of 'make' (faster, no installer)
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  CuReD Desktop Build" -ForegroundColor Cyan
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
    Write-Host "[2/3] Building Python server with PyInstaller..." -ForegroundColor Yellow
    Set-Location "$RootDir\server"

    # Install PyInstaller if not present
    python -m pip show pyinstaller | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Installing PyInstaller..." -ForegroundColor DarkYellow
        python -m pip install pyinstaller
    }

    pyinstaller cured-server.spec --noconfirm

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: PyInstaller build failed!" -ForegroundColor Red
        exit 1
    }

    # Verify output exists
    if (-not (Test-Path "$RootDir\server\dist\cured-server\cured-server.exe")) {
        Write-Host "ERROR: PyInstaller output not found at server\dist\cured-server\" -ForegroundColor Red
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
    Write-Host "Packaged app: electron\out\cured-desktop-win32-x64\" -ForegroundColor White
}
