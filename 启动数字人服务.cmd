@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_digital_human_stack.ps1"
if errorlevel 1 pause
