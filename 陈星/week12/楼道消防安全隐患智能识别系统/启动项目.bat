@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===================================
echo   楼道消防安全隐患智能识别系统
echo ===================================
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
) else (
    echo 未找到 .venv，尝试使用系统 Python ...
    py -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
)
echo.
echo 若上方报错，请先按 README 安装 requirements.txt
pause
