#!/usr/bin/env bash
cd "$(dirname "$0")/.."
if [ ! -x "venv/bin/python" ]; then
    echo "venv not found -- run linux/setup.sh first."
    read -p "Press Enter to close..."
    exit 1
fi
echo "Starting Brad's Agent Stack Creator..."
echo "Closing this window will stop the dashboard. The session daemon"
echo "(your Claude Code sessions) keeps running independently of it."
echo
./venv/bin/python app.py
read -p "Press Enter to close..."
