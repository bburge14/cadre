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

chmod +x "$REPO_DIR/macos/start.sh"

DESKTOP_DIR="$HOME/Desktop"
if [ -d "$DESKTOP_DIR" ]; then
    LAUNCHER="$DESKTOP_DIR/Start Cadre.command"
    cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
"$REPO_DIR/macos/start.sh"
EOF
    chmod +x "$LAUNCHER"
    echo "Desktop launcher created: $LAUNCHER"
    echo "(first double-click may prompt Right-click -> Open once, since it's an unsigned script -- normal Gatekeeper behavior)"
else
    echo "No Desktop folder found -- skipping the desktop launcher. Run macos/start.sh directly instead."
fi

echo
echo "Setup complete. Run macos/start.sh (or the Desktop icon) to launch the dashboard."
