@echo off
setlocal

rem 1. Switch to the repository directory and drive so settings.yaml, log.txt,
rem    and saved images land in the expected project folder.
rem 2. Activate the local venv first, then launch the main script with that
rem    interpreter so Windows uses the project's installed dependencies.
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Virtual environment not found.
    echo Run create_venv_windows.cmd first.
    exit /b 1
)

call "venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Could not activate the virtual environment.
    exit /b 1
)

python "%~dp0show_alerts"
exit /b %ERRORLEVEL%
