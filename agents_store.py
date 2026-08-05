from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

import config

AGENTS_DIR = config.CLAUDE_AGENTS_DIR
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass
class AgentFile:
    filename: str
    frontmatter: dict
    body: str

    @property
    def name(self) -> str:
        return self.frontmatter.get("name", self.filename.removesuffix(".md"))


def _path_for(filename: str) -> Path:
    safe = Path(filename).name
    if not safe.endswith(".md"):
        raise ValueError("agent filename must end in .md")
    return AGENTS_DIR / safe


def list_agents() -> list[AgentFile]:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    agents = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            agents.append(read_agent(path.name))
        except ValueError:
            continue
    return agents


def read_agent(filename: str) -> AgentFile:
    path = _path_for(filename)
    text = path.read_text()
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{filename} has no YAML frontmatter block")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).lstrip("\n")
    return AgentFile(filename=path.name, frontmatter=frontmatter, body=body)


def write_agent(filename: str, frontmatter: dict, body: str) -> None:
    name = frontmatter.get("name", "")
    if not NAME_RE.match(name):
        raise ValueError(
            "name must be lowercase letters/numbers with hyphens, e.g. 'my-agent'"
        )
    if not frontmatter.get("description", "").strip():
        raise ValueError("description is required")

    frontmatter = {k: v for k, v in frontmatter.items() if v not in (None, "", [])}
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    content = f"---\n{yaml_text}---\n\n{body.strip()}\n"

    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    _path_for(filename).write_text(content)


def delete_agent(filename: str) -> None:
    path = _path_for(filename)
    if path.exists():
        path.unlink()
