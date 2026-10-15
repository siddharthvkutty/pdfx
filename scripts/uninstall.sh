#!/usr/bin/env bash
# Removes pdfX and its menu entry. Ghostscript and LibreOffice are left in place.
set -euo pipefail

data="${XDG_DATA_HOME:-$HOME/.local/share}"
rm -rf "$data/pdfx"
rm -f "$data/applications/pdfx.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$data/applications" || true
echo "pdfX has been removed."
