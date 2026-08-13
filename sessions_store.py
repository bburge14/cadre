from __future__ import annotations

import json
import time
import uuid

import zlib

import config

STORE_FILE = config.SESSIONS_FILE

# Same idea as agents_store.avatar_for: deterministic (crc32, not the
# randomized-per-process hash()) so a session without a custom icon still
# looks visually distinct and stays on the same icon across restarts,
# without needing anything stored. A custom pick (session.icon) always
# wins over this -- see default_icon_for's callers.
ICON_CHOICES = [
    "🚀", "💻", "🎮", "🛠️", "📊", "🌐", "📝", "🎨",
    "🔬", "💬", "📈", "🏗️", "🛒", "📱", "🔐", "☁️",
    "🐛", "🧪", "📦", "🎯", "🔥", "🎵", "📷", "🏆",
    "⚡", "🗂️", "🔑", "🌟", "🧩", "📡", "🎓", "💰",
]


def default_icon_for(session_id: str) -> str:
    return ICON_CHOICES[zlib.crc32(session_id.encode()) % len(ICON_CHOICES)]


def _load() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    sessions = json.loads(STORE_FILE.read_text())
    for s in sessions:
        s.setdefault("provider", "claude")
        s.setdefault("internal", False)
        s.setdefault("icon", "")
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


def add(
    label: str, workdir: str, session_id: str | None = None, provider: str = "claude", internal: bool = False,
) -> dict:
    sessions = _load()
    entry = {
        "id": session_id or str(uuid.uuid4()),
        "label": label,
        "workdir": workdir,
        "provider": provider,
        "created_at": time.time(),
        # Never shown in the dashboard's own session list -- a session
        # Cadre spun up for its own internal use (e.g. driving Claude
        # Code's /mcp connector picker), not one the user asked to create
        # and manage themselves. Still a completely normal session
        # otherwise; nothing else treats this specially.
        "internal": internal,
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
