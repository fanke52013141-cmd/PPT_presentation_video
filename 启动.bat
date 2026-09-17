@echo off
setlocal enabledelayedexpansion
title PPT 视频工作台 (便携版)
cd /d "%~dp0"

rem ============================================================
rem  PPT 视频工作台 一键启动（便携版）
rem  - 使用包内 Python / Node / ffmpeg，不依赖系统安装
rem  - 不修改系统环境变量，关闭窗口即可停止服务
rem  - 本文件必须保持 ANSI(GBK) 编码：cmd 解析 UTF-8 批处理时会在
rem    多字节行上失去同步，把注释/回显片段当成命令执行
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

rem ---- 字幕设计字体：注册到当前用户字体表（幂等，无需管理员） ----
rem Remotion 只按字体名渲染字幕，字体不在 Windows 字体表里就会静默回退微软雅黑。
rem 注册脚本自身是 ASCII 编写的，失败不阻断启动。
if exist "%ROOT%scripts\portable_install_fonts.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\portable_install_fonts.ps1"
)

echo ============================================
echo   PPT 视频工作台 便携版
echo   地址:  http://127.0.0.1:%PPT_STUDIO_PORT%
echo   ffmpeg: 包内完整版（已强制指定）
echo   关闭本窗口即停止服务
echo ============================================
echo.

rem ---- 延迟 4 秒后自动打开浏览器 ----
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start "" http://127.0.0.1:%PPT_STUDIO_PORT%"

rem ---- 路径自适应：包被复制/移动到新位置后，自动修正包内本地资源绝对路径（幂等） ----
"%ROOT%runtime\python\python.exe" "%ROOT%scripts\portable_relocate.py"
if errorlevel 1 (
  echo [警告] 路径自适应脚本执行失败，本地素材引用可能失效，将继续启动。
)

rem ---- 前台启动服务（窗口显示运行日志） ----
"%ROOT%runtime\python\python.exe" "%ROOT%server.py"

echo.
echo 服务已退出。
pause
