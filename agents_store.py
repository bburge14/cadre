from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

import yaml

import config

AGENTS_DIR = config.CLAUDE_AGENTS_DIR
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


# Deterministic, not truly random -- a name always lands on the same
# emoji/color every time (a stable visual identity across page loads,
# not a fresh roll each render), while still looking arbitrary from a
# user's perspective since there's no visible logic tying an agent's
# role to its icon. zlib.crc32 instead of Python's built-in hash()
# specifically because str hashing is randomized per-process by default
# (PYTHONHASHSEED) -- the exact same agent name would get a different
# avatar after every single restart otherwise.
_AVATAR_EMOJI = [
    "🧑‍💻", "🧑‍🔬", "🧑‍🎨", "🧑‍🏫", "🧑‍⚖️", "🧑‍✈️", "🧑‍🚀", "🧑‍🌾",
    "🧑‍🍳", "🧑‍🔧", "🧑‍🏭", "🧑‍💼", "🧑‍🎤", "🧑‍🚒", "🧑‍⚕️", "🧑‍🎓",
    "🕵️", "👮", "💂", "🥷", "👷", "🧑", "🧒", "👦",
    "👧", "🧑‍🦰", "🧑‍🦱", "🧑‍🦳", "🧑‍🦲", "👴", "👵", "🙋",
    "🙆", "💁", "🙇", "🧘", "🚶", "🏃", "💃", "🕺",
    "🤹", "🏊", "🚴", "🧗", "⛷️", "🏄", "🤸", "🧍",
    "🤦", "🤷", "🧑‍🦯", "🧑‍🦽", "🧑‍🦼", "👳", "🧕", "🤵",
    "👰", "🤴", "👸", "🧑‍🤝‍🧑", "🙅", "🤱",
]
_AVATAR_COLORS = ["blue", "green", "orange", "teal", "purple", "amber", "pink", "red"]


def avatar_for(name: str) -> dict:
    h = zlib.crc32(name.encode())
    return {
        "emoji": _AVATAR_EMOJI[h % len(_AVATAR_EMOJI)],
        "color": _AVATAR_COLORS[(h // len(_AVATAR_EMOJI)) % len(_AVATAR_COLORS)],
    }


@dataclass
class AgentFile:
    filename: str
    frontmatter: dict
    body: str

    @property
    def name(self) -> str:
        return self.frontmatter.get("name", self.filename.removesuffix(".md"))


def project_agents_dir(workdir: str) -> Path:
    """Claude Code's own native per-project agent override location --
    agents here apply only to sessions rooted at this workdir, layered on
    top of (or overriding by name) the global ~/.claude/agents/ team."""
    return Path(workdir) / ".claude" / "agents"


def _path_for(filename: str, agents_dir: Path | None = None) -> Path:
    safe = Path(filename).name
    if not safe.endswith(".md"):
        raise ValueError("agent filename must end in .md")
    return (agents_dir or AGENTS_DIR) / safe


def list_agents(agents_dir: Path | None = None) -> list[AgentFile]:
    target = agents_dir or AGENTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    agents = []
    for path in sorted(target.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            agents.append(read_agent(path.name, agents_dir=target))
        except ValueError:
            continue
    return agents


def read_agent(filename: str, agents_dir: Path | None = None) -> AgentFile:
    path = _path_for(filename, agents_dir)
    text = path.read_text()
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{filename} has no YAML frontmatter block")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).lstrip("\n")
    return AgentFile(filename=path.name, frontmatter=frontmatter, body=body)


def write_agent(filename: str, frontmatter: dict, body: str, agents_dir: Path | None = None) -> None:
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

    target = agents_dir or AGENTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    _path_for(filename, target).write_text(content)


def delete_agent(filename: str, agents_dir: Path | None = None) -> None:
    path = _path_for(filename, agents_dir)
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


_SKILLS_START = "<!-- BEGIN AUTO-GENERATED SKILLS -->"
_SKILLS_END = "<!-- END AUTO-GENERATED SKILLS -->"
_SKILLS_BLOCK_RE = re.compile(
    re.escape(_SKILLS_START) + r".*?" + re.escape(_SKILLS_END) + r"\n*", re.DOTALL
)


def strip_skills_block(body: str) -> str:
    """Removes any existing auto-generated skills block so re-saving with a
    different skill selection doesn't stack blocks."""
    return _SKILLS_BLOCK_RE.sub("", body).lstrip("\n")


def build_skills_block(skills: list) -> str:
    """skills: a list of skills_store.SkillFile. Skills aren't wired into a
    subagent the way tools/spawn-permissions are (there's no equivalent
    frontmatter field Claude Code is confirmed to read for this) -- so this
    works the one way we know is reliable: plain instructions in the
    agent's own system prompt telling it what's available and to invoke by
    name when relevant."""
    if not skills:
        return ""
    lines = [f"{_SKILLS_START}\n## Skills available to you\n"]
    lines.append(
        "Invoke these by name when they apply to what you're doing:\n"
    )
    for skill in skills:
        description = skill.frontmatter.get("description", "")
        lines.append(f"- **{skill.name}**: {description}")
    lines.append(f"\n{_SKILLS_END}\n")
    return "\n".join(lines) + "\n"
