"""Best-effort translation of this app's Claude-format agent definitions
into the native subagent config formats the other three supported CLIs
have since shipped, so whichever provider a session actually runs, the
right subagent team is there in a format that CLI's own binary reads.
`.claude/agents/` stays the single source of truth (managed by
agents_store.py, unchanged) -- these three are always regenerated to
match it, one file per agent, never touching anything else that might
already live in that CLI's own agent directory (a subagent the user
created by hand, directly through that CLI).

Schemas below are as documented as of 2026-08 (see SETUP.md for
citations). Gemini's is the most directly verified against primary docs.
Codex's docs themselves flag standalone agent files not being picked up
in some builds. None of the three has been run against a real install by
this app's own author -- treat all three as best-effort until you've
actually tested one.

Deliberately NOT translated, and why:
- model / effort: cross-vendor model names aren't equivalent by string;
  omitted so each CLI uses its own default rather than being handed a
  meaningless value.
- Skills: each CLI's own skills mechanism (if it has one) uses a
  different file format from Claude's. Skill descriptions are folded
  into the instructions text instead (agents_store.build_skills_block()
  already does this for Claude; same block carries over verbatim here).
- Gemini specifically: subagents cannot delegate to other subagents at
  all (a hard architectural limit, not a gap in this translation) --
  Claude's Agent(x, y) spawn list has nothing to map to there. Tool
  restrictions aren't translated either, since Gemini's tool identifiers
  (read_file, grep_search, ...) aren't a confirmed match for Claude's
  (Read, Grep, ...) -- omitting the tools field means "inherit
  everything," a safe default rather than a guessed-wrong one.
"""
from __future__ import annotations

from pathlib import Path

import yaml

import agents_store


def root_for_agents_dir(agents_dir: Path) -> Path:
    """The stack's root directory (a project workdir, or the home
    directory for the global stack) -- derived from the Claude agents_dir
    already being passed around everywhere else, so no new parameter
    needs threading through every call site. Safe because only the
    *global* Claude dir is ever env-overridden (CLAUDE_AGENTS_DIR);
    project_agents_dir() is always exactly <workdir>/.claude/agents."""
    if agents_dir == agents_store.AGENTS_DIR:
        return Path.home()
    return agents_dir.parent.parent


def _codex_agents_dir(root: Path) -> Path:
    return root / ".codex" / "agents"


def _gemini_agents_dir(root: Path) -> Path:
    return root / ".gemini" / "agents"


def _kimi_agents_dir(root: Path) -> Path:
    return root / ".kimi-code" / "agents"


def _toml_string(value: str) -> str:
    """A TOML basic string, single-line (all newlines escaped) -- avoids
    every edge case a triple-quoted multi-line string has (a body that
    itself contains \"\"\", trailing-whitespace rules) at the cost of a
    less readable raw file. Correctness over prettiness for a generated
    config nobody's meant to hand-edit."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _write_codex_agent(agents_dir: Path, agent: agents_store.AgentFile) -> None:
    base_tools, _spawnable = agents_store.parse_tools(agent.frontmatter.get("tools", ""))
    # Codex's schema has no per-tool allowlist -- sandbox_mode is the
    # closest lever it exposes. Only mark read-only when there's truly
    # nothing that mutates or executes (Bash alone, with no Edit/Write,
    # still needs real access -- e.g. incident-responder running
    # diagnostic commands).
    read_only = bool(base_tools) and not any(t in base_tools for t in ("Edit", "Write", "Bash"))

    lines = [
        f"name = {_toml_string(agent.name)}",
        f'description = {_toml_string(agent.frontmatter.get("description", ""))}',
    ]
    if read_only:
        lines.append('sandbox_mode = "read-only"')
    lines.append(f"developer_instructions = {_toml_string(agent.body.strip())}")

    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{agent.name}.toml").write_text("\n".join(lines) + "\n")


def _write_gemini_agent(agents_dir: Path, agent: agents_store.AgentFile) -> None:
    frontmatter = {
        "name": agent.name,
        "description": agent.frontmatter.get("description", ""),
    }
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    content = f"---\n{yaml_text}---\n\n{agent.body.strip()}\n"

    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{agent.name}.md").write_text(content)


def _write_kimi_agent(agents_dir: Path, agent: agents_store.AgentFile, other_names: set) -> None:
    base_tools, spawnable = agents_store.parse_tools(agent.frontmatter.get("tools", ""))
    frontmatter = {
        "name": agent.name,
        "description": agent.frontmatter.get("description", ""),
    }
    if base_tools:
        # Kimi's own docs show Read/Grep/Glob as real tool identifiers --
        # the same names Claude uses -- so passing Claude's names through
        # unchanged is a reasonable best-effort match, not a confirmed
        # 1:1 mapping.
        frontmatter["tools"] = base_tools
    spawnable = [s for s in spawnable if s in other_names]
    if spawnable:
        frontmatter["subagents"] = spawnable
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    content = f"---\n{yaml_text}---\n\n{agent.body.strip()}\n"

    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / f"{agent.name}.md").write_text(content)


def sync_agent(agents_dir: Path, agent: agents_store.AgentFile, other_names: set) -> None:
    """Writes/overwrites this one agent's Codex/Gemini/Kimi equivalents.
    Only ever touches the file matching this agent's own name in each
    directory -- never wipes or lists the directory, so anything a user
    created there directly through one of those CLIs is left alone."""
    root = root_for_agents_dir(agents_dir)
    if not agent.name:
        return
    _write_codex_agent(_codex_agents_dir(root), agent)
    _write_gemini_agent(_gemini_agents_dir(root), agent)
    _write_kimi_agent(_kimi_agents_dir(root), agent, other_names)


def remove_agent(agents_dir: Path, agent_name: str) -> None:
    """Deletes exactly the one file matching agent_name in each of the
    three directories, if present -- same non-destructive scoping as
    sync_agent."""
    root = root_for_agents_dir(agents_dir)
    for path in (
        _codex_agents_dir(root) / f"{agent_name}.toml",
        _gemini_agents_dir(root) / f"{agent_name}.md",
        _kimi_agents_dir(root) / f"{agent_name}.md",
    ):
        if path.exists():
            path.unlink()


def sync_all(agents_dir: Path) -> None:
    """Re-syncs every agent currently in agents_dir -- used after a
    preset/library activation that can write several agents at once."""
    agents = agents_store.list_agents(agents_dir=agents_dir)
    names = {a.name for a in agents}
    for agent in agents:
        sync_agent(agents_dir, agent, names - {agent.name})
