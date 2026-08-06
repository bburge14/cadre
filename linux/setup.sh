#!/usr/bin/env bash
# One-time setup: creates the venv, installs dependencies, and drops a
# double-clickable launcher on the Desktop. Safe to re-run.
set -e
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

echo "Creating virtual environment..."
python3 -m venv venv
./venv/bin/pip install --upgrade pip >/dev/null
echo "Installing dependencies..."
./venv/bin/pip install -r requirements.txt

chmod +x "$REPO_DIR/linux/start.sh"

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ]; then
    LAUNCHER="$DESKTOP_DIR/Start Agent Stack Creator.desktop"
    cat > "$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=Start Agent Stack Creator
Comment=Launch Brad's Agent Stack Creator dashboard
Exec="$REPO_DIR/linux/start.sh"
Icon=utilities-terminal
Terminal=true
Categories=Development;
EOF
    chmod +x "$LAUNCHER"
    # GNOME/Nautilus refuses to run a freshly-written .desktop file until
    # it's marked trusted; harmless no-op on desktops that don't use gio.
    gio set "$LAUNCHER" metadata::trusted true 2>/dev/null || true
    echo "Desktop launcher created: $LAUNCHER"
    echo "(some desktop environments still need a one-time right-click -> \"Allow Launching\")"
else
    echo "No Desktop folder found -- skipping the desktop launcher. Run linux/start.sh directly instead."
fi

echo
echo "Setup complete. Run linux/start.sh (or the Desktop icon) to launch the dashboard."
