@echo off
chcp 65001 >nul
title PPT Visualization Studio
setlocal EnableExtensions

REM ---- 绝对路径，避开中文目录 %~dp0 解析问题 ----
set "PROJ=C:\Users\Administrator\Desktop\软件\PPT_presentation_video"
set "VENV=%PROJ%\.venv\Scripts\python.exe"

REM ---- ffmpeg discovery ----
set "FF_FOUND=0"
if defined PPT_STUDIO_FFMPEG_DIR (
  if exist "%PPT_STUDIO_FFMPEG_DIR%\ffmpeg.exe" if exist "%PPT_STUDIO_FFMPEG_DIR%\ffprobe.exe" set "FF_FOUND=1"
)
if %FF_FOUND%==0 (
  if exist "%PROJ%\tools\ffmpeg\bin\ffmpeg.exe" if exist "%PROJ%\tools\ffmpeg\bin\ffprobe.exe" (
    set "PPT_STUDIO_FFMPEG_DIR=%PROJ%\tools\ffmpeg\bin"
    set "FF_FOUND=1"
  )
)
if %FF_FOUND%==0 (
  where ffmpeg >nul 2>nul
  if not errorlevel 1 (
    where ffprobe >nul 2>nul
    if not errorlevel 1 set "FF_FOUND=2"
  )
)
if %FF_FOUND%==1 (
  set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
  echo [ffmpeg] using %PPT_STUDIO_FFMPEG_DIR%
) else if %FF_FOUND%==2 (
  for /f "delims=" %%F in ('where ffmpeg') do set "PPT_STUDIO_FFMPEG_DIR=%%~dpF"
  if "%PPT_STUDIO_FFMPEG_DIR:~-1%"=="\" set "PPT_STUDIO_FFMPEG_DIR=%PPT_STUDIO_FFMPEG_DIR:~0,-1%"
  echo [ffmpeg] using PATH: %PPT_STUDIO_FFMPEG_DIR%
) else (
  echo [warn] ffmpeg not found; video color validation / export may fail.
)

if not exist "%VENV%" (
  echo [error] .venv not found at %VENV%. Re-run the deployment step.
  pause
  exit /b 1
)

set "PYTHONPATH=%PROJ%"

REM ---- pick a free port (avoids "Address already in use" -> window flash) ----
set "PORT=8000"
for /f "delims=" %%P in ('"%VENV%" "%PROJ%\pick_port.py"') do set "PORT=%%P"
set "PPT_STUDIO_PORT=%PORT%"
echo [server] using port %PORT%

REM ---- open the browser a few seconds after boot ----
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:%PORT%"

echo [server] PPT Visualization Studio starting at http://127.0.0.1:%PORT%
echo [server] Keep this window open. Press Ctrl+C to stop the service.
"%VENV%" "%PROJ%\start_server.py"
if errorlevel 1 (
  echo [error] server exited with an error. See output above.
  pause
)
endlocal
