@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo The project environment is missing. Run: python -m venv .venv
    echo Then run: .venv\Scripts\python.exe -m pip install -e .
    pause
    exit /b 1
)
".venv\Scripts\pythonw.exe" "offline_redactor.py"
