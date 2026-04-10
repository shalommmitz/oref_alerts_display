@echo off
setlocal

rem 1. Always work from the repository directory so the venv lands in a
rem    predictable place even if the script is started from another folder.
rem 2. Use the Python 3.13 launcher target explicitly because Windows Python
rem    3.14 currently has a pygame installation issue for this project.
cd /d "%~dp0"

py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Could not find Python 3.13 via the Windows py launcher.
    echo Install Python 3.13 first, then re-run this script.
    echo This repository currently avoids Windows Python 3.14 because pygame installation is failing there.
    exit /b 1
)

if exist "venv" (
    rmdir /s /q "venv"
)

py -3.13 -m venv "venv"
if errorlevel 1 (
    echo Could not create the virtual environment.
    exit /b 1
)

(
    echo @echo off
    echo call "%%~dp0venv\Scripts\activate.bat"
) > "v.cmd"

call "venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo Could not upgrade pip/setuptools/wheel inside the virtual environment.
    exit /b 1
)

call "venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 (
    echo Could not install Python dependencies from requirements.txt.
    exit /b 1
)

set "CHECK_FILE=%TEMP%\phc_windows_venv_check_%RANDOM%_%RANDOM%.py"
(
    echo import importlib
    echo import sys
    echo try:
    echo     from zoneinfo import ZoneInfo
    echo except ImportError:
    echo     from backports.zoneinfo import ZoneInfo
    echo errors = []
    echo for module_name in ("yaml", "requests", "PIL", "pygame", "bidi", "tkinter"):
    echo     try:
    echo         importlib.import_module(module_name)
    echo     except Exception as exc:
    echo         errors.append(f"{module_name}: {exc}")
    echo try:
    echo     ZoneInfo("Asia/Jerusalem")
    echo except Exception as exc:
    echo     errors.append(f"zoneinfo Asia/Jerusalem: {exc}")
    echo if errors:
    echo     print("Dependency check failed after creating the virtual environment.", file=sys.stderr)
    echo     for error in errors:
    echo         print(f"  - {error}", file=sys.stderr)
    echo     sys.exit(1)
    echo print("Virtual environment is ready.")
) > "%CHECK_FILE%"

call "venv\Scripts\python.exe" "%CHECK_FILE%"
set "CHECK_ERROR=%ERRORLEVEL%"
del "%CHECK_FILE%" >nul 2>&1
if not "%CHECK_ERROR%"=="0" (
    exit /b %CHECK_ERROR%
)

echo.
echo Windows virtual environment is ready.
echo To launch the app, run:
echo   run_show_alerts_windows.cmd

exit /b 0
