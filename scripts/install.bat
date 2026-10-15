@echo off
rem Double-click to install pdfX. Runs install.ps1 with the policy bypassed, since Windows blocks .ps1 files by default.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
    echo.
    echo pdfX was not installed. Read the message above.
)
pause
