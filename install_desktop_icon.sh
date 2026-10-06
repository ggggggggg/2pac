#!/bin/bash
# -----------------------------------------------------------------------------
# Install 2PAC GUI Desktop Launcher
# -----------------------------------------------------------------------------
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
ICON_PATH="$SCRIPT_DIR/adr_gui_icon.png"
LAUNCHER_PATH="$SCRIPT_DIR/launch_gui.sh"

chmod +x "$LAUNCHER_PATH"

DESKTOP_ENTRY="[Desktop Entry]
Version=1.0
Type=Application
Name=2pac gui
Comment=Hardware Control & Telemetry GUI for 2PAC ADR
Exec=$LAUNCHER_PATH
Path=$SCRIPT_DIR
Icon=$ICON_PATH
Terminal=false
StartupWMClass=2pac_gui
StartupNotify=true
Categories=Utility;Science;"

mkdir -p "$HOME/.local/share/applications"
echo "$DESKTOP_ENTRY" > "$HOME/.local/share/applications/2pac_gui.desktop"
chmod +x "$HOME/.local/share/applications/2pac_gui.desktop"

if [ -d "$HOME/Desktop" ]; then
    echo "$DESKTOP_ENTRY" > "$HOME/Desktop/2pac_gui.desktop"
    chmod +x "$HOME/Desktop/2pac_gui.desktop"
    if command -v gio &> /dev/null; then
        gio set "$HOME/Desktop/2pac_gui.desktop" metadata::trusted true 2>/dev/null || true
    fi
fi

if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

echo "Successfully installed 2pac GUI desktop launcher!"
echo "Launcher location: $HOME/.local/share/applications/2pac_gui.desktop"
if [ -d "$HOME/Desktop" ]; then
    echo "Desktop shortcut: $HOME/Desktop/2pac_gui.desktop"
fi

