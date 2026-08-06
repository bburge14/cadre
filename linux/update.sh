#!/usr/bin/env bash
# Pulls the latest code, reinstalls dependencies (in case requirements.txt
# changed), and restarts the dashboard if this checkout owns a registered
# service -- the session daemon is deliberately left alone, since
# restarting it ends any live Claude Code sessions it's holding open; if an
# update specifically touches session_daemon.py, restart that yourself.
set -e
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "This isn't a git checkout (no .git/ found) -- can't pull an update"
    echo "this way. Download the latest release from GitHub instead:"
    echo "https://github.com/bburge14/brads-agent-stack-creator/releases"
    exit 1
fi

echo "Pulling latest changes..."
git pull

echo "Reinstalling dependencies..."
./venv/bin/pip install -r requirements.txt

# Same WorkingDirectory-match safety check as uninstall.sh -- a service
# name is global, not scoped to whichever checkout runs this script.
SERVICE_FILE="$HOME/.config/systemd/user/claude-session-daemon.service"
registered_dir=""
if [ -f "$SERVICE_FILE" ]; then
    registered_dir="$(grep '^WorkingDirectory=' "$SERVICE_FILE" | head -1 | cut -d= -f2-)"
    registered_dir="${registered_dir/#%h/$HOME}"
fi

if [ -n "$registered_dir" ] && [ "$registered_dir" = "$REPO_DIR" ]; then
    echo "Restarting claude-command-center.service (the dashboard only)..."
    systemctl --user restart claude-command-center.service
else
    echo
    echo "No matching systemd service for this checkout -- restart the"
    echo "dashboard yourself (re-run linux/start.sh, or close and reopen it)"
    echo "to pick up the new code."
fi

echo
echo "Done. Now on: v$(cat VERSION 2>/dev/null || echo unknown)"
