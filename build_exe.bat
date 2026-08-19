@echo off
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --onedir --noconsole --icon NONE --name "VictorPDFToolsBox" --hidden-import fitz --hidden-import pymupdf --hidden-import document_workspace --hidden-import audit_log --hidden-import stamp_library --hidden-import flow_layout --hidden-import runtime_deps --hidden-import win32com --hidden-import win32com.client --hidden-import pythoncom --hidden-import docx --hidden-import openpyxl --hidden-import lxml --hidden-import pytesseract --hidden-import pptx --distpath "C:\tmp\victor_pdf_dist" --workpath "C:\tmp\victor_pdf_build" qt_app.py
if errorlevel 1 goto build_failed

set "TOOLS_DIR=%USERPROFILE%\Desktop\Cursor Tools"
if not exist "%USERPROFILE%\Desktop" set "TOOLS_DIR=%CD%\VictorPDFToolsBox-desktop-copy"
if not exist "%TOOLS_DIR%" mkdir "%TOOLS_DIR%"
set "DESKTOP_DIR=%TOOLS_DIR%\VictorPDFToolsBox"
robocopy "C:\tmp\victor_pdf_dist\VictorPDFToolsBox" "%DESKTOP_DIR%" /E >nul
if errorlevel 8 goto copy_failed

echo.
echo EXE output:
echo C:\tmp\victor_pdf_dist\VictorPDFToolsBox\VictorPDFToolsBox.exe
echo.
echo Cursor Tools copy:
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
