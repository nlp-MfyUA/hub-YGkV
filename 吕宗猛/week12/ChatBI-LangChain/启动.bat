@echo off
chcp 65001 >nul
title ChatBI-LangChain
cd /d %~dp0
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

echo ============================================
echo   ChatBI-LangChain - natural language to SQL
echo   URL: http://127.0.0.1:8612/
echo   Close this window to stop the server
echo ============================================
echo.

if exist "C:\SoftWare\miniconda3\envs\py312\python.exe" (
    "C:\SoftWare\miniconda3\envs\py312\python.exe" main.py
) else (
    conda run -n py312 python main.py
)

if errorlevel 2 (
    start "" http://127.0.0.1:8612/
)
pause
