@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
if errorlevel 1 (
    echo.
    echo pdfX was not fully removed. Close it if it is open, then try again.
)
pause
