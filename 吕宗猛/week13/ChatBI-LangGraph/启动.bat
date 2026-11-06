@echo off
chcp 65001 >nul
title ChatBI-LangGraph
cd /d %~dp0
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

if not exist ".env" (
    echo [ChatBI-LangGraph] 未找到 .env，正在从 .env.example 创建……
    copy .env.example .env >nul
    echo   已创建 .env，请确认 BASE_URL / API_KEY 与 week12 一致后重新运行。
    echo.
)

echo ============================================
echo   ChatBI-LangGraph - natural language to SQL
echo   URL: http://127.0.0.1:8613/
echo   Close this window to stop the server
echo ============================================
echo.

if exist "C:\SoftWare\miniconda3\envs\py312\python.exe" (
    "C:\SoftWare\miniconda3\envs\py312\python.exe" main.py
) else (
    conda run -n py312 python main.py
)

if errorlevel 2 (
    start "" http://127.0.0.1:8613/
)
pause
