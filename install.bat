@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" uv venv --python 3.12 .venv
if errorlevel 1 exit /b 1
uv pip install --python ".venv\Scripts\python.exe" -r requirements-dev.txt
pause
