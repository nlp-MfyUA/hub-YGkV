@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

set "PY=C:\SoftWare\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=python"

title 心屿 · 情感陪伴（LangGraph）
echo ============================================
echo   心屿 · LangGraph 版
echo   后端：http://127.0.0.1:8622/
echo   前端：http://127.0.0.1:8612/
echo ============================================
echo.
echo [1/2] 启动后端进程...
start "心屿后端 (LangGraph)" /D "%~dp0backend" "%PY%" main.py
timeout /t 2 /nobreak >nul
echo [2/2] 启动前端进程...
start "心屿前端 (LangGraph)" /D "%~dp0frontend" "%PY%" main.py
timeout /t 2 /nobreak >nul
echo 打开页面...
start "" "http://127.0.0.1:8612/"
exit /b 0
