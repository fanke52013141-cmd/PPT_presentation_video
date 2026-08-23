@echo off
REM ---- Repair missing System32 in inherited PATH (so chcp/where/etc. work) ----
set "PATH=%SystemRoot%\System32;%SystemRoot%;%PATH%"
%SystemRoot%\System32\chcp.com 65001 >nul 2>nul
title PPT Visualization Studio
setlocal EnableExtensions

REM ---- Resolve project root relative to this bat (path-safe, no paren blocks) ----
set "PROJ=%~dp0"
if "%PROJ:~-1%"=="\" set "PROJ=%PROJ:~0,-1%"
cd /d "%PROJ%"
set "VENV=%PROJ%\.venv\Scripts\python.exe"

echo ===================================================
echo   PPT Visualization Studio - Local Web Service
echo   Project: %PROJ%
echo ===================================================
echo.

REM ---- [1/4] ffmpeg discovery (goto-style to survive parens in path) ----
echo [1/4] Checking ffmpeg/ffprobe...
REM ---- WinGet ffmpeg auto-detection (fills PPT_STUDIO_FFMPEG_DIR if installed via winget) ----
for /d %%P in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\*ffmpeg*") do (
  for /d %%V in ("%%P\*") do (
    if exist "%%V\bin\ffmpeg.exe" if exist "%%V\bin\ffprobe.exe" set "PPT_STUDIO_FFMPEG_DIR=%%V\bin"
  )
)
if defined PPT_STUDIO_FFMPEG_DIR if exist "%PPT_STUDIO_FFMPEG_DIR%\ffmpeg.exe" if exist "%PPT_STUDIO_FFMPEG_DIR%\ffprobe.exe" goto ffmpeg_from_env
if exist "%PROJ%\tools\ffmpeg\bin\ffmpeg.exe" if exist "%PROJ%\tools\ffmpeg\bin\ffprobe.exe" goto ffmpeg_from_tools
if exist "%PROJ%\runtime\ffmpeg\bin\ffmpeg.exe" if exist "%PROJ%\runtime\ffmpeg\bin\ffprobe.exe" goto ffmpeg_from_runtime
where ffmpeg >nul 2>nul
if errorlevel 1 goto ffmpeg_missing
where ffprobe >nul 2>nul
if errorlevel 1 goto ffmpeg_missing
echo [ffmpeg] using PATH
goto ffmpeg_done
:ffmpeg_from_env
set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
echo [ffmpeg] using env: %PPT_STUDIO_FFMPEG_DIR%
goto ffmpeg_done
:ffmpeg_from_tools
set "PPT_STUDIO_FFMPEG_DIR=%PROJ%\tools\ffmpeg\bin"
set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
echo [ffmpeg] using %PPT_STUDIO_FFMPEG_DIR%
goto ffmpeg_done
:ffmpeg_from_runtime
set "PPT_STUDIO_FFMPEG_DIR=%PROJ%\runtime\ffmpeg\bin"
set "PATH=%PPT_STUDIO_FFMPEG_DIR%;%PATH%"
echo [ffmpeg] using %PPT_STUDIO_FFMPEG_DIR%
goto ffmpeg_done
:ffmpeg_missing
echo [warn] ffmpeg/ffprobe not found; video color validation / export may fail.
:ffmpeg_done
echo.

REM ---- [2/4] venv + deps ----
echo [2/4] Checking Python environment...
if exist "%VENV%" goto venv_ok
echo [setup] venv not found, creating it at "%PROJ%\.venv" ...
py -m venv "%PROJ%\.venv"
if errorlevel 1 goto venv_failed
echo [setup] installing dependencies from requirements.txt ...
"%VENV%" -m pip install -r "%PROJ%\requirements.txt"
if errorlevel 1 goto deps_failed
echo [setup] dependencies installed.
goto venv_ok
:venv_failed
echo [error] could not create .venv. Run this shortcut as administrator, or create the venv manually.
pause
exit /b 1
:deps_failed
echo [error] dependency installation failed. See output above.
pause
exit /b 1
:venv_ok
echo [python] %VENV%
echo.

REM ---- [3/4] pick a free port ----
REM NOTE: relative paths + no inner quotes, because %PROJ% contains a space
REM       and a parenthesis ("Program Files (x86)") which break for /f quoting.
echo [3/4] Reserving a free port...
set "PORT=8000"
for /f "delims=" %%P in ('.venv\Scripts\python.exe pick_port.py') do set "PORT=%%P"
set "PPT_STUDIO_PORT=%PORT%"
echo [server] using port %PORT%
echo.

REM ---- [4/4] start ----
echo [4/4] Starting backend FastAPI server...
start "" cmd /c "timeout /t 4 /nobreak >nul && start http://127.0.0.1:%PORT%"

REM ---- digital human service (separate window, default :9001) ----
if not defined PPT_DIGITAL_HUMAN_PORT set "PPT_DIGITAL_HUMAN_PORT=9001"
if not defined PPT_DIGITAL_HUMAN_MOCK set "PPT_DIGITAL_HUMAN_MOCK=1"
set "DH_PORT_FREE=0"
for /f "delims=" %%F in ('.venv\Scripts\python.exe check_port_free.py %PPT_DIGITAL_HUMAN_PORT%') do set "DH_PORT_FREE=%%F"
if "%DH_PORT_FREE%"=="0" goto dh_busy
start "Digital Human Service (:%PPT_DIGITAL_HUMAN_PORT%, mock=%PPT_DIGITAL_HUMAN_MOCK%)" /min "%VENV%" "%PROJ%\digital_human_service.py"
echo [digital-human] starting on port %PPT_DIGITAL_HUMAN_PORT% (mock=%PPT_DIGITAL_HUMAN_MOCK%) ...
goto server_start
:dh_busy
echo [digital-human] port %PPT_DIGITAL_HUMAN_PORT% already in use - assume running, skip.
:server_start
echo [server] PPT Visualization Studio starting at http://127.0.0.1:%PORT%
echo [server] Keep this window open. Press Ctrl+C to stop the service.
echo.
set "PYTHONPATH=%PROJ%"
"%VENV%" "%PROJ%\start_server.py"
if not errorlevel 1 goto end_ok
echo.
echo [error] server exited with an error. See output above.
pause
exit /b 1
:end_ok
endlocal
