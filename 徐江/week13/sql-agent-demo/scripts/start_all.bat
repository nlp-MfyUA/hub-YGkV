@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  SQL Agent 一键启动：后端 + 前端（各自独立窗口）
REM
REM  用法：
REM    start_all.bat          正常模式（DeepSeek，需配置 Key）
REM    start_all.bat --mock   离线 mock 模式（无需 Key）
REM
REM  会在两个新控制台窗口中分别启动后端（8000）与前端（8501），
REM  关闭对应窗口即停止该服务。
REM ============================================================

set "MOCK_ARG="
if /i "%~1"=="--mock" set "MOCK_ARG=--mock"

cd /d %~dp0..

echo 正在启动 SQL Agent 后端 ...
start "" /D "%CD%\scripts" cmd /k start_backend.bat %MOCK_ARG%

echo 正在启动 SQL Agent 前端 ...
start "" /D "%CD%\scripts" cmd /k start_frontend.bat

echo.
echo ============================================================
echo   后端 : http://127.0.0.1:8000     API 文档 /docs
echo   前端 : http://localhost:8501     浏览器自动打开
if defined MOCK_ARG echo   模式 : mock 离线模式（无需 API Key）
echo ============================================================
echo.
echo 提示：关闭对应的控制台窗口即可停止该服务。
pause
