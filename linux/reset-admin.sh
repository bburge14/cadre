#!/usr/bin/env bash
# Resets the admin account so you can pick a new username/password --
# for when you're locked out and the password itself is genuinely
# unrecoverable (hashed one-way, never stored in plaintext anywhere).
# Only removes instance/admin.json -- your sessions list, agent stacks,
# skills, and settings (everything else in instance/) are untouched, and
# no restart is needed: admin_exists() is a live file check, so the very
# next page load redirects straight to /setup. Pass -y/--yes to skip the
# confirmation prompt.
set -e
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

if [ ! -f "$REPO_DIR/instance/admin.json" ]; then
    echo "No admin account is set up yet -- nothing to reset."
    echo "Just load the dashboard; it'll take you to /setup directly."
    exit 0
fi

if [ "$1" != "-y" ] && [ "$1" != "--yes" ]; then
    echo "This deletes instance/admin.json only -- your sessions, agent"
    echo "stacks, skills, and settings are untouched. The next time anyone"
    echo "loads the dashboard, they land on /setup to create a new account."
    echo
    read -p "Continue? [y/N] " confirm
    case "$confirm" in
        y|Y|yes|YES) ;;
        *) echo "Aborted."; exit 1 ;;
    esac
fi

rm -f "$REPO_DIR/instance/admin.json"

echo
echo "Done. Load the dashboard now -- it'll take you straight to /setup."
