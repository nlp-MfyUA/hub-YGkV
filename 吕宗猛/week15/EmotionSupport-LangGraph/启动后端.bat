@echo off
chcp 65001 >nul
cd /d %~dp0
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1

set "PY=C:\SoftWare\miniconda3\envs\py312\python.exe"
if not exist "%PY%" set "PY=python"

title 心屿后端 · LangGraph
echo 后端进程：http://127.0.0.1:8622/
"%PY%" main.py
pause
