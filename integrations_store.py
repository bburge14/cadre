"""Integrations: a named credential (API key, token, webhook URL, anything
else that's just a secret string) that gets injected as an environment
variable into any session whose stack has opted into it -- see
session_daemon.py's _spawn() for where that actually happens. Deliberately
simple: no OAuth, no per-service schema, just name + env var + value,
mirroring settings.py's own plaintext-JSON-with-0600-perms convention
rather than inventing encryption this app doesn't use anywhere else.
"""
from __future__ import annotations

import json
import time
import uuid

import config

STORE_FILE = config.INSTANCE_DIR / "integrations.json"


def _load() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    return json.loads(STORE_FILE.read_text())


def _save(integrations: list[dict]) -> None:
    STORE_FILE.write_text(json.dumps(integrations, indent=2))
    STORE_FILE.chmod(0o600)


def list_integrations() -> list[dict]:
    return _load()


def get(integration_id: str) -> dict | None:
    for i in _load():
        if i["id"] == integration_id:
            return i
    return None


def add(name: str, env_var: str, value: str) -> dict:
    integrations = _load()
    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "env_var": env_var,
        "value": value,
        "created_at": time.time(),
    }
    integrations.append(entry)
    _save(integrations)
    return entry


def update(integration_id: str, **fields) -> dict | None:
    integrations = _load()
    for i in integrations:
        if i["id"] == integration_id:
            i.update({k: v for k, v in fields.items() if v is not None})
            _save(integrations)
            return i
    return None


def remove(integration_id: str) -> None:
    integrations = [i for i in _load() if i["id"] != integration_id]
    _save(integrations)
