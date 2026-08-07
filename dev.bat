@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ACTION=%~1"

if not "%ACTION%"=="" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%dev.ps1" %ACTION%
    set "EXIT_CODE=%ERRORLEVEL%"

    if "%ACTION%"=="desktop" if "%EXIT_CODE%"=="0" (
        echo.
        echo Services are running. Press any key to close this window.
        pause >nul
    )

    exit /b %EXIT_CODE%
)

:menu
cls
echo.
echo =================================
echo   Interview Agent 开发服务管理
echo =================================
echo.
echo   1. 启动桌面版 (Tauri)
echo   2. 启动浏览器版 (后端 8000 / 前端 4173)
echo   3. 停止所有服务
echo   4. 查看服务状态
echo   5. 查看日志
echo   0. 退出
echo.
set "ACTION="
set /p "CHOICE=请输入数字并回车: "

if "%CHOICE%"=="1" set "ACTION=desktop"
if "%CHOICE%"=="2" set "ACTION=start"
if "%CHOICE%"=="3" set "ACTION=stop"
if "%CHOICE%"=="4" set "ACTION=status"
if "%CHOICE%"=="5" set "ACTION=logs"
if "%CHOICE%"=="0" exit /b 0

if "%ACTION%"=="" (
    echo 无效输入，请重新选择。
    pause >nul
    goto menu
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%dev.ps1" %ACTION%
echo.
pause
goto menu