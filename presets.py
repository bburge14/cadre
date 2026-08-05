from __future__ import annotations

import json
from pathlib import Path

import yaml

import agents_store
import config

PRESETS_DIR = config.BASE_DIR / "presets"
MANIFEST_FILE = PRESETS_DIR / "manifest.json"


def list_presets() -> list[dict]:
    return json.loads(MANIFEST_FILE.read_text())


def _template_path(agent_id: str) -> Path:
    return PRESETS_DIR / f"{agent_id}.md"


def _read_template(path: Path) -> tuple[dict, str] | None:
    text = path.read_text()
    match = agents_store.FRONTMATTER_RE.match(text)
    if not match:
        return None
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).lstrip("\n")
    return frontmatter, body


def list_library_agents() -> list[agents_store.AgentFile]:
    agents = []
    for path in sorted(PRESETS_DIR.glob("*.md")):
        parsed = _read_template(path)
        if parsed is None:
            continue
        frontmatter, body = parsed
        agents.append(agents_store.AgentFile(filename=path.name, frontmatter=frontmatter, body=body))
    return agents


def activate(agent_ids: list[str]) -> list[str]:
    """Copies each requested template into ~/.claude/agents/. Returns the
    filenames actually written."""
    written = []
    for agent_id in agent_ids:
        parsed = _read_template(_template_path(agent_id))
        if parsed is None:
            continue
        frontmatter, body = parsed
        filename = f"{agent_id}.md"
        agents_store.write_agent(filename, frontmatter, body)
        written.append(filename)
    return written


def activate_preset(preset_id: str) -> list[str]:
    for preset in list_presets():
        if preset["id"] == preset_id:
            return activate(preset["agents"])
    raise ValueError(f"Unknown preset: {preset_id}")
