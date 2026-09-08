@echo off
chcp 65001 >nul
echo 正在停止 PPT 视频工作台服务...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -match 'server\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('已停止 PID ' + $_.ProcessId) }"
echo 完成。
timeout /t 2 /nobreak >nul
