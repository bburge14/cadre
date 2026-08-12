from __future__ import annotations

import json
import time
import uuid

import config

STORE_FILE = config.INSTANCE_DIR / "agent_stacks.json"

# The one always-present team (~/.claude/agents, not tied to any project
# directory) that Claude Code falls back to for any session not covered
# by a more specific stack -- synthesized by app.py's _resolve_stack, not
# a real row in this store. Shared here (rather than only living in
# app.py) so session_daemon.py's workflow runner can recognize it too
# without importing app.py itself.
GLOBAL_STACK_ID = "global"


def _load() -> list[dict]:
    if not STORE_FILE.exists():
        return []
    stacks = json.loads(STORE_FILE.read_text())
    for s in stacks:
        s.setdefault("integration_ids", [])
        # Every stack always has exactly one assigned provider -- there's
        # no "ask each time" state anymore (confirmed via direct feedback
        # 2026-08-12: a stack should just always answer this, same as it
        # already answers which directory/team to use; the manual picker
        # on New Session is for when there's no stack at all, not for a
        # stack that hasn't made up its mind). Any stack saved before this
        # existed defaults to claude, same as everything already did.
        s.setdefault("default_provider", "claude")
    return stacks


def _save(stacks: list[dict]) -> None:
    STORE_FILE.write_text(json.dumps(stacks, indent=2))
    STORE_FILE.chmod(0o600)


def list_stacks() -> list[dict]:
    return _load()


def get(stack_id: str) -> dict | None:
    for s in _load():
        if s["id"] == stack_id:
            return s
    return None


def add(name: str, workdir: str, default_provider: str = "claude") -> dict:
    stacks = _load()
    entry = {
        "id": str(uuid.uuid4()),
        "name": name,
        "workdir": workdir,
        "default_provider": default_provider,
        "created_at": time.time(),
    }
    stacks.append(entry)
    _save(stacks)
    return entry


def update(stack_id: str, **fields) -> dict | None:
    stacks = _load()
    for s in stacks:
        if s["id"] == stack_id:
            s.update({k: v for k, v in fields.items() if v is not None})
            _save(stacks)
            return s
    return None


def remove(stack_id: str) -> None:
    stacks = [s for s in _load() if s["id"] != stack_id]
    _save(stacks)
