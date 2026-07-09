@echo off
title PPT Visualization Studio Launcher
cd /d "%~dp0"
echo ===================================================
echo   PPT Visualization Studio - Local Web Service
echo   Soft Pastel Studio
echo ===================================================
echo.

echo [1/4] Checking ffmpeg/ffprobe...
if defined PPT_STUDIO_FFMPEG_DIR (
    if exist "%PPT_STUDIO_FFMPEG_DIR%\ffmpeg.exe" if exist "%PPT_STUDIO_FFMPEG_DIR%\ffprobe.exe" (
        set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
        goto ffmpeg_ready
    )
)
if exist "%~dp0tools\ffmpeg\bin\ffmpeg.exe" if exist "%~dp0tools\ffmpeg\bin\ffprobe.exe" (
    set "PPT_STUDIO_FFMPEG_DIR=%~dp0tools\ffmpeg\bin"
    set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
    goto ffmpeg_ready
)
if exist "%~dp0runtime\ffmpeg\bin\ffmpeg.exe" if exist "%~dp0runtime\ffmpeg\bin\ffprobe.exe" (
    set "PPT_STUDIO_FFMPEG_DIR=%~dp0runtime\ffmpeg\bin"
    set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
    goto ffmpeg_ready
)
if exist "%~dp0..\work\runtime\ffmpeg\bin\ffmpeg.exe" if exist "%~dp0..\work\runtime\ffmpeg\bin\ffprobe.exe" (
    set "PPT_STUDIO_FFMPEG_DIR=%~dp0..\work\runtime\ffmpeg\bin"
    set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
    goto ffmpeg_ready
)
if exist "%~dp0..\work\runtime\ffmpeg\ffmpeg.exe" if exist "%~dp0..\work\runtime\ffmpeg\ffprobe.exe" (
    set "PPT_STUDIO_FFMPEG_DIR=%~dp0..\work\runtime\ffmpeg"
    set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
    goto ffmpeg_ready
)
if exist "%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\vm\tools\app\ffmpeg\ffmpeg.exe" if exist "%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\vm\tools\app\ffmpeg\ffprobe.exe" (
    set "PPT_STUDIO_FFMPEG_DIR=%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\vm\tools\app\ffmpeg"
    set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
    goto ffmpeg_ready
)
where ffmpeg >nul 2>nul
if %ERRORLEVEL% neq 0 echo [WARN] ffmpeg was not found. Video render color validation may fail.
where ffprobe >nul 2>nul
if %ERRORLEVEL% neq 0 echo [WARN] ffprobe was not found. Video render color validation may fail.
goto ffmpeg_done
:ffmpeg_ready
echo Using ffmpeg tools: %PPT_STUDIO_FFMPEG_DIR%
:ffmpeg_done
echo.

echo [2/4] Checking Python dependencies...
py -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Failed to install python dependencies. Please make sure Python is installed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [3/4] Starting backend FastAPI server...
start "" http://localhost:8000
py server.py

pause
