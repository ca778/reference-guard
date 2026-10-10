@echo off
chcp 65001 >nul
echo Close the Reference Guard window with Ctrl+C first.
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" restore_original.py
pause
