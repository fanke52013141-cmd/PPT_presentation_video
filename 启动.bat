@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title PPT 视频工作台 (便携版)
cd /d "%~dp0"

rem ============================================================
rem  PPT 视频工作台 一键启动（便携版）
rem  - 使用包内 Python / Node / ffmpeg，不依赖系统安装
rem  - 不修改系统环境变量，关闭窗口即可停止服务
rem ============================================================

rem ---- 包内工具路径（最高优先级） ----
set "ROOT=%~dp0"
set "FFMPEG_BINARY=%ROOT%tools\ffmpeg\bin\ffmpeg.exe"
set "FFPROBE_BINARY=%ROOT%tools\ffmpeg\bin\ffprobe.exe"
set "PPT_STUDIO_HOST=127.0.0.1"
set "PPT_STUDIO_PORT=8000"

rem ---- 把包内 Node / ffmpeg 追加到本会话 PATH（Remotion 需要 npx） ----
set "PATH=%ROOT%runtime\node;%ROOT%tools\ffmpeg\bin;%PATH%"

rem ---- 校验关键文件存在 ----
if not exist "%ROOT%runtime\python\python.exe" (
  echo [错误] 缺少 runtime\python\python.exe，请确认解压完整。
  pause
  exit /b 1
)
if not exist "%ROOT%runtime\node\node.exe" (
  echo [错误] 缺少 runtime\node\node.exe，请确认解压完整。
  pause
  exit /b 1
)
if not exist "%FFMPEG_BINARY%" (
  echo [错误] 缺少 tools\ffmpeg\bin\ffmpeg.exe，请确认解压完整。
  pause
  exit /b 1
)

rem ---- 可选：首次自动注册包内字幕字体（仅当前用户，无需管理员） ----
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\portable_install_fonts.ps1" >nul 2>&1

echo ============================================
echo   PPT 视频工作台 便携版
echo   地址:  http://127.0.0.1:%PPT_STUDIO_PORT%
echo   ffmpeg: 包内完整版 7.1.1（已强制指定）
echo   关闭本窗口即停止服务
echo ============================================
echo.

rem ---- 延迟 4 秒后自动打开浏览器 ----
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start "" http://127.0.0.1:%PPT_STUDIO_PORT%"

rem ---- 前台启动服务（窗口显示运行日志） ----
"%ROOT%runtime\python\python.exe" "%ROOT%server.py"

echo.
echo 服务已退出。
pause
