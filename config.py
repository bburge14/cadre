from __future__ import annotations

import secrets
import sys
from pathlib import Path

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-frozen executable (see windows/*.spec):
    # bundled read-only data (templates/, presets/, static/) is extracted
    # to sys._MEIPASS, a transient directory that can be wiped/regenerated
    # on every launch -- writable state (instance/, .env) must NOT live
    # there. Keep it in the same stable location a normal source install
    # already uses, so both packaging methods share one data directory.
    BUNDLE_DIR = Path(sys._MEIPASS)
    BASE_DIR = Path.home() / ".claude" / "cadre"
    BASE_DIR.mkdir(parents=True, exist_ok=True)
else:
    BUNDLE_DIR = Path(__file__).parent
    BASE_DIR = Path(__file__).parent

load_dotenv(BASE_DIR / ".env")

import os

INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

# CADRE_* is the canonical name; COMMAND_CENTER_* (the app's pre-rename
# name) still works as a fallback so an existing .env from before the
# rename keeps working untouched.
def _env(new_key: str, old_key: str, default: str) -> str:
    return os.environ.get(new_key, os.environ.get(old_key, default))


HOST = _env("CADRE_HOST", "COMMAND_CENTER_HOST", "127.0.0.1")
PORT = int(_env("CADRE_PORT", "COMMAND_CENTER_PORT", "7420"))
DAEMON_PORT = int(_env("CADRE_DAEMON_PORT", "COMMAND_CENTER_DAEMON_PORT", "7421"))
TERMINAL_PORT = int(_env("CADRE_TERMINAL_PORT", "COMMAND_CENTER_TERMINAL_PORT", "7422"))
COOKIE_SECURE = _env("CADRE_COOKIE_SECURE", "COMMAND_CENTER_COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")

_agents_dir_override = os.environ.get("CLAUDE_AGENTS_DIR", "").strip()
CLAUDE_AGENTS_DIR = Path(_agents_dir_override) if _agents_dir_override else Path.home() / ".claude" / "agents"

SESSIONS_FILE = INSTANCE_DIR / "sessions.json"
ADMIN_FILE = INSTANCE_DIR / "admin.json"
SECRET_KEY_FILE = INSTANCE_DIR / "secret_key"
OAUTH_TOKENS_FILE = INSTANCE_DIR / "oauth_tokens.json"
SETTINGS_FILE = INSTANCE_DIR / "settings.json"

# GitHub/GitLab OAuth credentials and PROJECTS_ROOT are NOT read here --
# they're user-editable at runtime via the in-app Settings page, backed by
# settings.py/instance/settings.json, with these env vars only used as an
# initial fallback default the first time each is looked up. See settings.py.


def _load_or_create_secret_key() -> str:
    env_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if env_key:
        return env_key
    if SECRET_KEY_FILE.exists():
        return SECRET_KEY_FILE.read_text().strip()
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(key)
    SECRET_KEY_FILE.chmod(0o600)
    return key


SECRET_KEY = _load_or_create_secret_key()
