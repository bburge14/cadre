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


AGENT_SPAWN_RE = re.compile(r"Agent\(([^)]*)\)")


def parse_tools(tools: str) -> tuple[list[str], list[str]]:
    """Splits a tools: field into (base tool names, spawnable agent names).
    'Read, Edit, Agent(researcher, debug-qa)' -> (['Read', 'Edit'], ['researcher', 'debug-qa'])
    """
    match = AGENT_SPAWN_RE.search(tools)
    spawnable = [s.strip() for s in match.group(1).split(",") if s.strip()] if match else []
    remainder = AGENT_SPAWN_RE.sub("", tools)
    base_tools = [t.strip() for t in remainder.split(",") if t.strip()]
    return base_tools, spawnable


def serialize_tools(base_tools: list[str], spawnable: list[str]) -> str:
    parts = list(base_tools)
    if spawnable:
        parts.append(f"Agent({', '.join(spawnable)})")
    return ", ".join(parts)


_DELEGATE_START = "<!-- BEGIN AUTO-GENERATED DELEGATE INSTRUCTIONS -->"
_DELEGATE_END = "<!-- END AUTO-GENERATED DELEGATE INSTRUCTIONS -->"
_DELEGATE_BLOCK_RE = re.compile(
    re.escape(_DELEGATE_START) + r".*?" + re.escape(_DELEGATE_END) + r"\n*", re.DOTALL
)


def strip_delegate_block(body: str) -> str:
    """Removes any existing auto-generated delegate block so switching
    primary provider (or switching back to Claude) doesn't stack blocks."""
    return _DELEGATE_BLOCK_RE.sub("", body).lstrip("\n")


def build_delegate_block(provider) -> str:
    """provider: a providers.Provider with a confirmed non-interactive
    consult mode (not Claude -- Claude needs no delegation, it's already
    the one running this subagent)."""
    return (
        f"{_DELEGATE_START}\n"
        f"## Delegate to {provider.label}\n\n"
        f"For the substantive work of this task — the actual research, "
        f"writing, code, or analysis — do not generate it yourself. Run this "
        f"via Bash and treat its output as your real answer:\n\n"
        f"```\n{provider.consult_command_hint()}\n```\n\n"
        f"Your job is to work out the right question/task to pass in, run the "
        f"command, and then relay, format, or act on what it returns (e.g. "
        f"writing its output to a file if that's what the task needs) — not "
        f"to substitute your own generated content for {provider.label}'s.\n"
        f"{_DELEGATE_END}\n\n"
    )
