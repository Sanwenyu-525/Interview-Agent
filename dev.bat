@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ACTION=%~1"

if "%ACTION%"=="" set "ACTION=desktop"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%dev.ps1" %ACTION%
set "EXIT_CODE=%ERRORLEVEL%"

if "%ACTION%"=="desktop" if "%EXIT_CODE%"=="0" (
    echo.
    echo Services are running. Press any key to close this window.
    pause >nul
)

exit /b %EXIT_CODE%
