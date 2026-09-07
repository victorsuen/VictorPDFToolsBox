@echo off
cd /d "%~dp0"
python build_desktop.py
if errorlevel 1 goto build_failed
pause
exit /b 0

:build_failed
echo.
echo Build failed.
pause
exit /b 1
