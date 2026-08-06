#!/usr/bin/env bash
# Full teardown of this app's install footprint, so you can re-run
# macos/setup.sh and get a genuinely clean first-run experience. Removes
# only what setup.sh creates -- your source code, ~/.claude/agents/ (the
# global agent team), and every stack's own project directory are never
# touched. Pass -y/--yes to skip the confirmation prompt.
set -e
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

if [ "$1" != "-y" ] && [ "$1" != "--yes" ]; then
    echo "This will:"
    echo "  - stop the dashboard and session daemon if running (ends any"
    echo "    Claude Code sessions the daemon is currently holding open)"
    echo "  - delete venv/, instance/ (your admin account, sessions list,"
    echo "    agent stacks, settings), .env, and the Desktop launcher"
    echo
    echo "NOT touched: the source code itself, ~/.claude/agents/ (your global"
    echo "agent team), and every stack's own project directory."
    echo
    read -p "Continue? [y/N] " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
fi

echo "Stopping any running app.py / session_daemon.py processes..."
pkill -f "$REPO_DIR/app.py" 2>/dev/null || true
pkill -f "$REPO_DIR/session_daemon.py" 2>/dev/null || true

echo "Removing venv/, instance/, .env..."
rm -rf "$REPO_DIR/venv" "$REPO_DIR/instance" "$REPO_DIR/.env"

rm -f "$HOME/Desktop/Start Agent Stack Creator.command"

echo
echo "Done. Run macos/setup.sh to reinstall from scratch."
