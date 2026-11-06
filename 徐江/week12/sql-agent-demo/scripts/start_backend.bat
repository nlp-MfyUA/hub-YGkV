@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

REM ============================================================
REM  SQL Agent 后端启动脚本（FastAPI + uvicorn）
REM
REM  用法：
REM    start_backend.bat                正常模式（DeepSeek，需配置 Key）
REM    start_backend.bat --mock         离线 mock 模式（无需 Key）
REM    start_backend.bat --port 8080    指定端口（默认 8000）
REM
REM  组合示例：start_backend.bat --mock --port 8080
REM ============================================================

set "PORT=8000"
set "USE_MOCK="

:parse_args
if "%~1"=="" goto args_done
if /i "%~1"=="--mock" set "USE_MOCK=1"
if /i "%~1"=="--port" (
    if not "%~2"=="" (
        set "PORT=%~2"
        shift
    )
)
shift
goto parse_args
:args_done

if defined USE_MOCK set "LLM_PROVIDER=mock"

cd /d %~dp0..

REM ---- 激活 conda 环境 py312（优先 conda info --base，找不到则用默认安装路径）----
set "CONDA_BASE="
for /f "delims=" %%i in ('conda info --base 2^>nul') do set "CONDA_BASE=%%i"
if not defined CONDA_BASE set "CONDA_BASE=D:\ProgramData\anaconda3"
if not exist "%CONDA_BASE%\Scripts\activate.bat" (
    echo [ERROR] 未找到 conda 安装目录：%CONDA_BASE%
    echo         请确认已安装 Anaconda，且存在 py312 环境。
    pause
    exit /b 1
)
call "%CONDA_BASE%\Scripts\activate.bat" py312
if errorlevel 1 (
    echo [ERROR] conda 环境 py312 激活失败，请检查该环境是否存在：
    echo         conda env list
    pause
    exit /b 1
)

REM ---- 修复无效的 SSL_CERT_FILE ------------------------------------------
REM conda activate 可能把 SSL_CERT_FILE 指向不存在的路径（本机 py312 即如此：
REM 激活脚本指向 <env>\ssl\cacert.pem，实际 cacert 在 <env>\Library\ssl\ 下），
REM 会导致 openai/httpx 在创建客户端时直接崩溃。此处校验并自愈。
if not defined SSL_CERT_FILE goto ssl_check_done
if exist "%SSL_CERT_FILE%" goto ssl_check_done
if exist "%CONDA_PREFIX%\Library\ssl\cacert.pem" (
    set "SSL_CERT_FILE=%CONDA_PREFIX%\Library\ssl\cacert.pem"
    goto ssl_fixed_redirect
)
set "SSL_CERT_FILE="
echo [fix] SSL_CERT_FILE 原路径无效且未找到替代 cacert，已清除该变量
goto ssl_check_done
:ssl_fixed_redirect
echo [fix] SSL_CERT_FILE 原路径无效，已重定向到: %SSL_CERT_FILE%
:ssl_check_done

if defined USE_MOCK (
    set "MODE_TEXT=mock 离线模式（无需 API Key）"
) else (
    set "MODE_TEXT=DeepSeek 真实 API（需在 config.local.yaml 配置 llm.api_key）"
)

echo ============================================================
echo   SQL Agent 后端（FastAPI + uvicorn）
echo   工作目录 : %CD%
echo   运行模式 : !MODE_TEXT!
echo   监听端口 : %PORT%
echo   API 文档 : http://127.0.0.1:%PORT%/docs
echo   健康检查 : http://127.0.0.1:%PORT%/api/health
echo ============================================================
echo.

uvicorn backend.app:app --host 127.0.0.1 --port %PORT%
if errorlevel 1 (
    echo.
    echo [ERROR] 后端启动失败。常见原因：端口 %PORT% 已被占用。
    echo         可换端口重试：start_backend.bat --port 8080
    pause
    exit /b 1
)
