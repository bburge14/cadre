#!/usr/bin/env bash
# Full teardown of this app's install footprint, so you can re-run
# linux/setup.sh and get a genuinely clean first-run experience. Removes
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
    echo "  - disable/remove the claude-command-center / claude-session-daemon"
    echo "    systemd --user services, if you installed them"
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

# Match by name AND confirm the registered unit actually points at *this*
# checkout before touching it -- systemd unit names are global, not scoped
# to whichever directory happens to be running the script, so a second
# checkout of this repo (or a scratch copy, as found the hard way) must
# never be able to reach across and kill a different install's services.
# SETUP.md's unit file uses the literal %h specifier (systemd's own
# shorthand for $HOME, expanded by systemd at run time, not pre-expanded in
# the file) so it has to be resolved by hand before comparing.
SERVICE_FILE="$HOME/.config/systemd/user/claude-session-daemon.service"
registered_dir=""
if [ -f "$SERVICE_FILE" ]; then
    registered_dir="$(grep '^WorkingDirectory=' "$SERVICE_FILE" | head -1 | cut -d= -f2-)"
    registered_dir="${registered_dir/#%h/$HOME}"
fi
if [ -n "$registered_dir" ] && [ "$registered_dir" = "$REPO_DIR" ]; then
    echo "Stopping and removing systemd services..."
    systemctl --user disable --now claude-command-center.service claude-session-daemon.service 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/claude-command-center.service" "$SERVICE_FILE"
    systemctl --user daemon-reload 2>/dev/null || true
elif [ -n "$registered_dir" ]; then
    echo "A claude-session-daemon service is registered but points at a different"
    echo "checkout ($registered_dir) -- leaving it alone."
    echo "Stopping any running app.py / session_daemon.py processes in this checkout..."
    pkill -f "$REPO_DIR/app.py" 2>/dev/null || true
    pkill -f "$REPO_DIR/session_daemon.py" 2>/dev/null || true
else
    echo "Stopping any running app.py / session_daemon.py processes..."
    pkill -f "$REPO_DIR/app.py" 2>/dev/null || true
    pkill -f "$REPO_DIR/session_daemon.py" 2>/dev/null || true
fi

echo "Removing venv/, instance/, .env..."
rm -rf "$REPO_DIR/venv" "$REPO_DIR/instance" "$REPO_DIR/.env"

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
rm -f "$DESKTOP_DIR/Start Agent Stack Creator.desktop"

echo
echo "Done. Run linux/setup.sh to reinstall from scratch."
