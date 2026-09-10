@echo off
cd /d "%~dp0"

echo ============================================
echo   Deep Research Assistant - starting...
echo ============================================

:: Use the conda env "course" if it exists (where deps were installed)
set PY=python
if exist "E:\Conda\envs\course\python.exe" set PY=E:\Conda\envs\course\python.exe
echo Using Python: %PY%

:: Check dependencies, install if missing
%PY% -X utf8 -c "import openai, httpx, dotenv, fastapi, uvicorn" 2>nul
if errorlevel 1 (
    echo [MISSING DEPS] installing requirements.txt ...
    %PY% -m pip install -r requirements.txt
)

echo.
echo Open in browser: http://127.0.0.1:8000
echo Press Ctrl+C to stop.
echo.

%PY% -X utf8 -m uvicorn api:app --port 8000

pause
