"""Workflows: a saved task (prompt + target Agent Stack) that can be run
on demand or, eventually, on a schedule -- see session_daemon.py's
_run_workflow() for what actually happens when one fires. This module is
pure CRUD, deliberately mirroring stacks_store.py's shape (same plain-
JSON-file, uuid-id, update-by-kwargs pattern) rather than inventing a new
one.
"""
from __future__ import annotations

import json
import time
import uuid

import config

STORE_FILE = config.INSTANCE_DIR / "workflows.json"


def _load() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    return json.loads(STORE_FILE.read_text())


def _save(workflows: list[dict]) -> None:
    STORE_FILE.write_text(json.dumps(workflows, indent=2))
    STORE_FILE.chmod(0o600)


def list_workflows() -> list[dict]:
    return _load()


def get(workflow_id: str) -> dict | None:
    for w in _load():
        if w["id"] == workflow_id:
            return w
    return None


def add(
    name: str, stack_id: str, prompt: str, provider: str,
    trigger_type: str = "manual", schedule: str | None = None,
    session_mode: str = "fresh", unattended: bool = False,
) -> dict:
    workflows = _load()
    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "stack_id": stack_id,
        "prompt": prompt,
        "provider": provider,
        "trigger_type": trigger_type,
        "schedule": schedule,
        "session_mode": session_mode,
        "pinned_session_id": None,
        "unattended": unattended,
        "enabled": True,
        "created_at": time.time(),
        "last_run_at": None,
        "last_run_status": None,
        "last_run_session_id": None,
    }
    workflows.append(entry)
    _save(workflows)
    return entry


def update(workflow_id: str, **fields) -> dict | None:
    workflows = _load()
    for w in workflows:
        if w["id"] == workflow_id:
            w.update({k: v for k, v in fields.items() if v is not None})
            _save(workflows)
            return w
    return None


def clear_pinned_session(workflow_id: str) -> None:
    """update()'s **fields filters out None (so it can't be used to clear
    a field back to None) -- this is the one place that legitimately needs
    to, when a "reuse" workflow's stack/provider changes enough that its
    previously pinned session no longer makes sense to resume."""
    workflows = _load()
    for w in workflows:
        if w["id"] == workflow_id:
            w["pinned_session_id"] = None
    _save(workflows)


def remove(workflow_id: str) -> None:
    workflows = [w for w in _load() if w["id"] != workflow_id]
    _save(workflows)
