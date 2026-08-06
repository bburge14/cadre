"""Claude Code Skills -- a different mechanism from agents_store.py's
subagents. A skill is a reusable, packaged set of instructions loaded into
whatever session invokes it (the top-level coordinator or a subagent),
not a separate spawned worker. Stored one directory per skill,
<skills-dir>/<name>/SKILL.md, mirroring the same global
(~/.claude/skills/) vs. per-project (<workdir>/.claude/skills/) scoping
agents_store.py already uses -- confirmed against real SKILL.md files
already on this machine (Codex's skills, which use the same
name/description frontmatter + markdown body convention Anthropic's
Skills spec defines), but never yet verified against Claude Code's own
skill-loading behavior for real.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_DIR = Path.home() / ".claude" / "skills"
NAME_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass
class SkillFile:
    name: str  # the directory name -- canonical identity, fixed once created
    frontmatter: dict
    body: str


def project_skills_dir(workdir: str) -> Path:
    """Claude Code's per-project skills location, mirroring
    agents_store.project_agents_dir -- skills here apply only to sessions
    rooted at this workdir, layered on top of ~/.claude/skills/."""
    return Path(workdir) / ".claude" / "skills"


def _skill_md_path(name: str, skills_dir: Path | None = None) -> Path:
    return (skills_dir or SKILLS_DIR) / name / "SKILL.md"


def _parse(text: str) -> tuple[dict, str] | None:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).lstrip("\n")
    return frontmatter, body


def list_skills(skills_dir: Path | None = None) -> list[SkillFile]:
    target = skills_dir or SKILLS_DIR
    target.mkdir(parents=True, exist_ok=True)
    skills = []
    for entry in sorted(target.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        md_path = entry / "SKILL.md"
        if not md_path.exists():
            continue
        parsed = _parse(md_path.read_text())
        if parsed is None:
            continue
        frontmatter, body = parsed
        skills.append(SkillFile(name=entry.name, frontmatter=frontmatter, body=body))
    return skills


def read_skill(name: str, skills_dir: Path | None = None) -> SkillFile:
    path = _skill_md_path(name, skills_dir)
    parsed = _parse(path.read_text())
    if parsed is None:
        raise ValueError(f"{name}/SKILL.md has no valid frontmatter")
    frontmatter, body = parsed
    return SkillFile(name=name, frontmatter=frontmatter, body=body)


def write_skill(name: str, description: str, body: str, skills_dir: Path | None = None) -> None:
    if not NAME_RE.match(name):
        raise ValueError(
            "name must be lowercase letters/numbers with hyphens, e.g. 'pdf-fill'"
        )
    if not description.strip():
        raise ValueError("description is required")

    frontmatter = {"name": name, "description": description.strip()}
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    content = f"---\n{yaml_text}---\n\n{body.strip()}\n"

    path = _skill_md_path(name, skills_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def delete_skill(name: str, skills_dir: Path | None = None) -> None:
    skill_dir = (skills_dir or SKILLS_DIR) / name
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
