# Removes pdfX and its Start Menu shortcut. Ghostscript and LibreOffice are left in place.
$ErrorActionPreference = "Stop"
$dir = Join-Path $env:LOCALAPPDATA "pdfX"
$shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\pdfX.lnk"

Remove-Item $shortcut -ErrorAction SilentlyContinue
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }  # fails with a clear message if pdfX is still open
Write-Host "pdfX has been removed."
