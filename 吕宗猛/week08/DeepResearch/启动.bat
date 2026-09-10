@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   深度研究助手 - 一键启动
echo ============================================
echo.
echo [1/3] 停止已占用 8000 端口的旧服务...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue; Write-Host ('  已停止 PID ' + $_) }"
ping -n 2 127.0.0.1 >nul
echo.
echo [2/3] 启动服务...
if not exist ".venv\Scripts\python.exe" (
    echo [错误] 未找到 .venv\Scripts\python.exe
    echo        请先执行: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
if not exist "main.py" (
    echo [错误] 未找到 main.py，请确认本文件放在项目根目录
    pause
    exit /b 1
)
start "DeepResearch" /min cmd /c ".venv\Scripts\python.exe main.py > server.log 2>&1"

echo [3/3] 等待服务就绪...
set /a i=0
:wait_loop
ping -n 2 127.0.0.1 >nul
curl -s -o nul http://127.0.0.1:8000/ && goto :ready
set /a i+=1
if %i% GEQ 15 goto :timeout
goto :wait_loop

:ready
echo.
echo 服务已就绪: http://127.0.0.1:8000/   (登录: admin / admin123)
echo 正在打开浏览器...
start "" http://127.0.0.1:8000/
endlocal & exit /b 0

:timeout
echo.
echo [错误] 15 秒内服务未就绪，server.log 末尾如下：
type server.log 2>nul
pause
exit /b 1
