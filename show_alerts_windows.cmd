@echo off
setlocal

rem 1. Keep this as the closest Windows analogue to `./show_alerts`.
rem 2. Delegate to the fuller launcher so there is only one place that owns
rem    the activation and repo-directory behavior.
cd /d "%~dp0"
call "%~dp0run_show_alerts_windows.cmd"
exit /b %ERRORLEVEL%
