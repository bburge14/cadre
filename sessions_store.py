from __future__ import annotations

import json
import time
import uuid

import config

STORE_FILE = config.SESSIONS_FILE


def _load() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    sessions = json.loads(STORE_FILE.read_text())
    for s in sessions:
        s.setdefault("provider", "claude")
    return sessions


def _save(sessions: list[dict]) -> None:
    STORE_FILE.write_text(json.dumps(sessions, indent=2))
    STORE_FILE.chmod(0o600)


def list_sessions() -> list[dict]:
    return _load()


def get(session_id: str) -> dict | None:
    for s in _load():
        if s["id"] == session_id:
            return s
    return None


def add(label: str, workdir: str, session_id: str | None = None, provider: str = "claude") -> dict:
    sessions = _load()
    entry = {
        "id": session_id or str(uuid.uuid4()),
        "label": label,
        "workdir": workdir,
        "provider": provider,
        "created_at": time.time(),
    }
    sessions.append(entry)
    _save(sessions)
    return entry


def update(session_id: str, **fields) -> dict | None:
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            s.update({k: v for k, v in fields.items() if v is not None})
            _save(sessions)
            return s
    return None


def remove(session_id: str) -> None:
    sessions = [s for s in _load() if s["id"] != session_id]
    _save(sessions)
