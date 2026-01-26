@echo off
setlocal enableextensions enabledelayedexpansion

:: Check for Admin privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [PHASE] Requesting administrative privileges...
    :: Use cmd /k to keep the window open so user sees the progress!
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process cmd -ArgumentList '/k \"%~dpnx0\"' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

:: 1. Check WSL
echo [PHASE] Checking WSL status...
wsl -d Ubuntu -e true >nul 2>&1
if %errorlevel% neq 0 (
    echo [PHASE] Ubuntu not found. Installing...
    :: This might prompt the user, but it's unavoidable for first-time setup
    echo.
    echo ================================================================
    echo  IMPORTANT INSTRUCTION
    echo ================================================================
    echo  1. A new window or prompt will appear asking for a UNIX username.
    echo  2. Create your username and password.
    echo  3. IMPORTANT: After creating the user, you will see a prompt like:
    echo     username@ComputerName:~$
    echo  4. TYPE "exit" AND PRESS ENTER to return to this installer.
    echo ================================================================
    echo.
    pause
    wsl --install -d Ubuntu
    timeout /t 10 > nul
    
    :: CHECK IF REBOOT IS NEEDED
    wsl -d Ubuntu -e true >nul 2>&1
    if %errorlevel% neq 0 (
        echo [PHASE] System Reboot Required!
        echo.
        echo ================================================================
        echo  SYSTEM REBOOT REQUIRED
        echo ================================================================
        echo  Windows Subsystem for Linux - WSL components have been enabled.
        echo  You MUST restart your computer to complete the installation.
        echo.
        echo  Please reboot now and run BEn App again.
        echo ================================================================
        pause
        exit
    )
)

:: 2. Files are bundled locally - no download needed
echo [PHASE] Using bundled configuration files...

:: 3. Run the internal setup (install docker inside WSL)
echo [PHASE] Configuring Ubuntu...
:: ensure line endings
wsl -d Ubuntu --user root sed -i 's/\r$//' ./install-ubuntu.bash
:: Run the script. This script installs docker if missing, checks plugin, and runs compose up.
echo [PHASE] Starting Docker Containers (this may take a while)...
wsl -d Ubuntu --user root bash ./install-ubuntu.bash
