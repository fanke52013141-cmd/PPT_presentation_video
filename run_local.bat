@echo off
title PPT Visualization Studio Launcher
echo ===================================================
echo   PPT Visualization Studio - Local Web Service
echo   Hand-drawn Sketch Style
echo ===================================================
echo.

echo [1/3] Checking Python dependencies...
py -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to install python dependencies. Please make sure Python is installed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/3] Starting backend FastAPI server...
start "" http://localhost:8000
py server.py

pause
