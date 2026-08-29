@echo off
chcp 65001 >nul 2>&1
title 启动 Elasticsearch 9.5.2
set "ES_BAT=g:\elasticsearch-9.5.2\bin\elasticsearch.bat"
set "ES_URL=http://127.0.0.1:9200"

echo ============================================
echo   Elasticsearch 9.5.2 启动脚本
echo ============================================
echo.

REM 1. 先检查 ES 是否已在运行，避免重复启动
curl -s -o nul --max-time 2 %ES_URL% >nul 2>&1
if %errorlevel%==0 (
    echo [提示] ES 已经在运行，无需重复启动。
    goto :show_info
)

REM 2. 启动 ES（最小化窗口）
echo 正在启动 Elasticsearch ...
start "Elasticsearch" /min "%ES_BAT%"

REM 3. 轮询等待 9200 就绪
echo 等待 9200 端口就绪 ...
set "count=0"
:wait
timeout /t 3 >nul
set /a count+=1
curl -s -o nul --max-time 2 %ES_URL% >nul 2>&1
if %errorlevel%==0 goto :ready
if %count% geq 20 (
    echo.
    echo [超时] 60 秒内 ES 未就绪。
    echo 请查看日志：g:\elasticsearch-9.5.2\logs\elasticsearch.log
    pause
    exit /b 1
)
echo   第 %count% 次检查，未就绪 ...
goto :wait

:ready
echo.
echo [成功] ES 已就绪！

:show_info
echo.
echo --- 连接信息 ---
echo 地址：%ES_URL%
echo.
echo 版本信息：
curl -s --max-time 3 %ES_URL%
echo.
echo 已加载插件：
curl -s --max-time 3 "%ES_URL%/_cat/plugins?v"
echo.
echo ============================================
echo  ES 在后台最小化窗口运行，请保持其开着。
echo  关闭该最小化窗口 = 停止 ES 服务。
echo ============================================
echo.
pause
