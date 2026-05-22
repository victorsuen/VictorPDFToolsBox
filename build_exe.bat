@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onedir --console --icon NONE --name "VictorPDFToolsBox" --distpath "C:\tmp\victor_pdf_dist" --workpath "C:\tmp\victor_pdf_build" qt_app.py
if errorlevel 1 goto build_failed

set "DESKTOP_DIR=%USERPROFILE%\Desktop\VictorPDFToolsBox"
if not exist "%USERPROFILE%\Desktop" set "DESKTOP_DIR=%CD%\VictorPDFToolsBox-desktop-copy"
robocopy "C:\tmp\victor_pdf_dist\VictorPDFToolsBox" "%DESKTOP_DIR%" /MIR >nul
if errorlevel 8 goto copy_failed

echo.
echo EXE output:
echo C:\tmp\victor_pdf_dist\VictorPDFToolsBox\VictorPDFToolsBox.exe
echo.
echo Desktop copy:
echo %DESKTOP_DIR%\VictorPDFToolsBox.exe
pause
exit /b 0

:build_failed
echo.
echo Build failed.
pause
exit /b 1

:copy_failed
echo.
echo Build succeeded, but desktop copy failed.
pause
exit /b 1
