@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Prefer the interpreter bundled in the green package; fall back to a system
rem Python for source checkouts.
set "PY=%~dp0python\python.exe"
if exist "%PY%" goto run

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo   No Python found / 没有找到 Python
    echo   Install Python 3.11+ from https://www.python.org/downloads/
    echo   安装时请勾选 "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)
set "PY=python"

:run
"%PY%" -m umegkmas %*
