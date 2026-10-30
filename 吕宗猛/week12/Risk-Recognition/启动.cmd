@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
if exist "%~dp0.venv\Scripts\python.exe" set PY=%~dp0.venv\Scripts\python.exe
if not defined PY (
    for %%i in (python.exe) do set PY=%%~$PATH:i
)
if not defined PY (
    echo [ERROR] 未找到 python，请先安装 Python 3.11+ 或加入 PATH
    pause
    exit /b 1
)
echo 启动楼道消防风险识别服务...
"%PY%" "%~dp0app.py" -HttpPort 8000 -HttpsPort 8443
pause
