"""User-editable runtime settings (GitHub/GitLab OAuth apps, projects root),
stored in instance/settings.json and editable from the in-app Settings page
-- no config-file editing or restart required. Falls back to an environment
variable of the same name (upper-cased) if a setting was never set through
the UI, for anyone who prefers .env-based config.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import config

_DEFAULTS = {
    "github_client_id": "",
    "github_client_secret": "",
    "gitlab_base_url": "https://gitlab.com",
    "gitlab_client_id": "",
    "gitlab_client_secret": "",
    "projects_root": str(Path.home() / "projects"),
    "gemini_api_key": "",
    "codex_api_key": "",
    "kimi_api_key": "",
    "default_provider": "claude",
    "terminal_theme": "auto",
}

_ENV_FALLBACK = {key: key.upper() for key in _DEFAULTS}


def _load() -> dict:
    if not config.SETTINGS_FILE.exists():
        return {}
    return json.loads(config.SETTINGS_FILE.read_text())


def _save(data: dict) -> None:
    config.SETTINGS_FILE.write_text(json.dumps(data, indent=2))
    config.SETTINGS_FILE.chmod(0o600)


def get(key: str) -> str:
    stored = _load().get(key, "")
    stored = stored.strip() if isinstance(stored, str) else stored
    if stored:
        return stored
    env_val = os.environ.get(_ENV_FALLBACK.get(key, ""), "").strip()
    if env_val:
        return env_val
    return _DEFAULTS.get(key, "")


def get_all() -> dict:
    return {key: get(key) for key in _DEFAULTS}


def update(**fields) -> None:
    data = _load()
    for key, value in fields.items():
        if key not in _DEFAULTS:
            raise ValueError(f"Unknown setting: {key}")
        data[key] = value.strip() if isinstance(value, str) else value
    _save(data)


def projects_root() -> Path:
    root = Path(get("projects_root"))
    root.mkdir(parents=True, exist_ok=True)
    return root
