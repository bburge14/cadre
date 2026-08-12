"""User-created preset bundles -- same shape as the bundled presets in
presets/manifest.json (id/name/description/agents/division), but stored
in the instance directory since these are per-install user data, not
something shipped with (or overwritten by) the app itself.
"""
from __future__ import annotations

import json
import time
import uuid

import config

STORE_FILE = config.INSTANCE_DIR / "custom_presets.json"


def _load() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    return json.loads(STORE_FILE.read_text())


def _save(presets: list[dict]) -> None:
    STORE_FILE.write_text(json.dumps(presets, indent=2))
    STORE_FILE.chmod(0o600)


def list_custom_presets() -> list[dict]:
    return _load()


def get(preset_id: str) -> dict | None:
    for p in _load():
        if p["id"] == preset_id:
            return p
    return None


def add(name: str, description: str, agents: list[str]) -> dict:
    presets = _load()
    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "agents": agents,
        "is_custom": True,
        "created_at": time.time(),
    }
    presets.append(entry)
    _save(presets)
    return entry


def remove(preset_id: str) -> None:
    presets = [p for p in _load() if p["id"] != preset_id]
    _save(presets)
