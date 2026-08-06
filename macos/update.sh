#!/usr/bin/env bash
# Pulls the latest code and reinstalls dependencies (in case
# requirements.txt changed). No services concept exists on macOS in this
# app (see SETUP.md) -- just restart the dashboard yourself afterward.
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

echo
echo "Done. Now on: v$(cat VERSION 2>/dev/null || echo unknown)"
echo "Restart the dashboard yourself (re-run macos/start.sh, or close and"
echo "reopen it) to pick up the new code."
