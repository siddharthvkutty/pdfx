#!/usr/bin/env bash
# Installs pdfX for the current user: a private Python environment, Ghostscript, and an application-menu entry.
# Safe to run again; it updates an existing install.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
dir="$data/pdfx"
apps="$data/applications"

# pm_install <name on Debian/Ubuntu/openSUSE> <name on Fedora/Arch>
pm_install() {
    local sudo=""
    [ "$(id -u)" -ne 0 ] && sudo="sudo"
    if command -v apt-get >/dev/null; then $sudo apt-get install -y "$1"
    elif command -v dnf >/dev/null; then $sudo dnf install -y "$2"
    elif command -v pacman >/dev/null; then $sudo pacman -S --noconfirm --needed "$2"
    elif command -v zypper >/dev/null; then $sudo zypper --non-interactive install "$1"
    else return 1
    fi
}

# 1. Python 3.10 or newer
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "pdfX needs Python 3.10 or newer (python3). Install it with your package manager and run this again." >&2
    exit 1
fi

# 2. Virtual environment and pdfX itself
mkdir -p "$dir"
if [ ! -x "$dir/venv/bin/python" ]; then
    # Debian and Ubuntu ship venv as a separate package
    python3 -m venv "$dir/venv" || {
        rm -rf "$dir/venv"
        command -v apt-get >/dev/null && { [ "$(id -u)" -eq 0 ] || echo "Installing python3-venv (needs sudo)..."; pm_install python3-venv python3-venv; }
        python3 -m venv "$dir/venv"
    }
fi
"$dir/venv/bin/python" -m pip install --upgrade "$repo"

# 3. Ghostscript, used by Compress
if ! command -v gs >/dev/null; then
    echo "Installing Ghostscript (needs sudo)..."
    pm_install ghostscript ghostscript || echo "Could not install Ghostscript. Install it with your package manager to use Compress." >&2
fi

# 4. Qt's X11 backend needs this library; it is missing on some fresh Ubuntu installs. Best effort.
# (grep without -q: with pipefail, an early-exiting grep would make ldconfig fail with SIGPIPE)
if ! ldconfig -p 2>/dev/null | grep libxcb-cursor >/dev/null; then
    pm_install libxcb-cursor0 xcb-util-cursor || echo "Could not install libxcb-cursor. If pdfX will not start on X11, install it." >&2
fi

# 5. Application-menu entry. The file name must stay pdfx.desktop: pdfX tells the desktop that name (Wayland taskbar icon).
"$dir/venv/bin/python" "$repo/scripts/make_icon.py" "$dir/pdfx.png"
mkdir -p "$apps"
cat > "$apps/pdfx.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=pdfX
Comment=PDF toolkit
Exec="$dir/venv/bin/pdfx"
Icon=$dir/pdfx.png
Terminal=false
Categories=Office;
StartupWMClass=pdfX
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true

echo
echo "pdfX is installed. Find it in your application menu, or run: $dir/venv/bin/pdfx"
