from __future__ import annotations

import json
from pathlib import Path

import yaml

import agent_formats
import agents_store
import config
import providers
import skills_store

PRESETS_DIR = config.BUNDLE_DIR / "presets"
MANIFEST_FILE = PRESETS_DIR / "manifest.json"
DIVISIONS_FILE = PRESETS_DIR / "divisions.json"

# Which default skills each preset agent should start with, by name --
# looked up against whatever's actually in the skills library at
# activation time (not baked statically into the template files) so a
# skill the user deleted just doesn't get attached, rather than
# referencing something that no longer exists.
AGENT_SKILL_HINTS: dict[str, list[str]] = {
    "python-engineer": [
        "code-review-checklist", "test-writing-guidelines", "error-handling-philosophy",
        "security-review-checklist", "dependency-upgrade-checklist", "api-design-consistency",
        "commit-message-style",
    ],
    "frontend-engineer": [
        "code-review-checklist", "test-writing-guidelines", "error-handling-philosophy",
        "security-review-checklist", "dependency-upgrade-checklist", "accessibility-checklist",
        "commit-message-style",
    ],
    "generalist-engineer": [
        "code-review-checklist", "test-writing-guidelines", "error-handling-philosophy",
        "security-review-checklist", "dependency-upgrade-checklist", "sql-query-review",
        "commit-message-style",
    ],
    "debug-qa": [
        "code-review-checklist", "test-writing-guidelines", "bug-report-reproduction-steps",
        "commit-message-style",
    ],
    "ci-cd-engineer": [
        "infrastructure-change-safety", "security-review-checklist", "dependency-upgrade-checklist",
        "commit-message-style",
    ],
    "infra-engineer": [
        "infrastructure-change-safety", "security-review-checklist", "dependency-upgrade-checklist",
        "runbook-format", "commit-message-style",
    ],
    "incident-responder": [
        "incident-postmortem-format", "bug-report-reproduction-steps", "runbook-format",
    ],
    "data-engineer": [
        "data-validation-checklist", "sql-query-review", "error-handling-philosophy",
        "commit-message-style",
    ],
    "data-scientist": [
        "data-validation-checklist", "notebook-hygiene", "commit-message-style",
    ],
    "data-analyst": [
        "data-validation-checklist", "notebook-hygiene", "sql-query-review",
        "presentation-of-findings", "commit-message-style",
    ],
    "writer": ["fact-checking-checklist", "outline-before-drafting", "writing-tone-guide"],
    "editor": ["fact-checking-checklist", "writing-tone-guide"],
    "analyst": ["fact-checking-checklist", "presentation-of-findings"],
    "researcher": ["research-source-checklist"],
    "project-scribe": ["writing-tone-guide"],
}


def attach_default_skills(agent_id: str, frontmatter: dict, body: str) -> tuple[dict, str]:
    hints = AGENT_SKILL_HINTS.get(agent_id, [])
    if not hints:
        return frontmatter, body
    available = {s.name: s for s in skills_store.list_skills()}
    matched = [available[name] for name in hints if name in available]
    if not matched:
        return frontmatter, body
    frontmatter = dict(frontmatter)
    frontmatter["skills"] = ", ".join(s.name for s in matched)
    body = agents_store.build_skills_block(matched) + agents_store.strip_skills_block(body)
    return frontmatter, body


_CONTINUITY_START = "<!-- BEGIN CADRE CONTINUITY NUDGE -->"
_CONTINUITY_END = "<!-- END CADRE CONTINUITY NUDGE -->"
_CONTINUITY_BLOCK = (
    f"{_CONTINUITY_START}\n"
    "Before starting work in this project, check for `PROJECT_STATUS.md` "
    "(or `STATUS.md`/`HANDOFF.md`) at the project root and read it first "
    "if it exists — it's kept current by another agent specifically so a "
    "fresh session doesn't have to re-derive context that's already been "
    "captured.\n"
    f"{_CONTINUITY_END}\n"
)


def ensure_continuity_nudge(root: Path) -> None:
    """Claude Code auto-loads CLAUDE.md into every session rooted at
    `root`, but nothing auto-loads PROJECT_STATUS.md -- without this, a
    fresh session (or a hand-off from a bloated one) never actually
    checks it unless someone remembers to say so, and project-scribe's
    whole point (skip re-deriving context another session already
    captured) doesn't take effect until the *next* session already knows
    to look. Idempotent (marker-delimited) and additive-only -- never
    touches whatever else is already in CLAUDE.md."""
    path = root / "CLAUDE.md"
    existing = path.read_text().rstrip() if path.exists() else ""
    if _CONTINUITY_START in existing:
        return
    separator = "\n\n" if existing else ""
    path.write_text(existing + separator + _CONTINUITY_BLOCK)


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


def load_divisions() -> dict:
    """filename -> division label (e.g. "Sales", "Security"), purely a
    library-browsing/filter grouping -- deliberately NOT part of any
    individual preset's own frontmatter, so activating an agent never
    copies this UI-only metadata into the live agent file a CLI actually
    reads. A preset missing from this file just isn't grouped (shows
    under "Other" in the library filter) rather than erroring."""
    if not DIVISIONS_FILE.exists():
        return {}
    return json.loads(DIVISIONS_FILE.read_text())


# Reputation-based, not independently verified end-to-end against a real
# install the way Claude is (see README/docs.html's Gemini/Codex/Kimi
# caveat) -- Codex is positioned specifically around coding, Gemini's
# standout is its large context window (favors research/document-heavy
# work), Claude covers everything else as the general-purpose default.
# Also drives actual activation now (see activate() below), not just the
# "Recommended" hint on an agent's own edit page -- direct correction
# 2026-08-15: the original ask was for activation to auto-select this,
# not just display it, and it was never wired up that far the first
# time around.
_DIVISION_RECOMMENDED_PROVIDER = {
    "Engineering": "codex",
    "Testing": "codex",
    "Data": "gemini",
}
_AGENT_RECOMMENDED_PROVIDER_OVERRIDES = {
    "researcher": "gemini",
    "product-trend-researcher": "gemini",
    "finance-investment-researcher": "gemini",
    "legal-document-review": "gemini",
    "specialized-document-generator": "gemini",
    "data-consolidation-agent": "gemini",
    "testing-evidence-collector": "gemini",
}


def recommended_provider(agent_name: str) -> str:
    if agent_name in _AGENT_RECOMMENDED_PROVIDER_OVERRIDES:
        return _AGENT_RECOMMENDED_PROVIDER_OVERRIDES[agent_name]
    division = load_divisions().get(f"{agent_name}.md", "")
    return _DIVISION_RECOMMENDED_PROVIDER.get(division, "claude")


def list_library_agents() -> list[agents_store.AgentFile]:
    agents = []
    for path in sorted(PRESETS_DIR.glob("*.md")):
        parsed = _read_template(path)
        if parsed is None:
            continue
        frontmatter, body = parsed
        agents.append(agents_store.AgentFile(filename=path.name, frontmatter=frontmatter, body=body))
    return agents


def activate(agent_ids: list[str], agents_dir: Path | None = None) -> list[str]:
    """Copies each requested template into agents_dir (default: the global
    ~/.claude/agents/). Returns the filenames actually written.

    Each agent's primary_provider is auto-set to its recommended_provider
    if -- and only if -- that provider is actually usable right now
    (installed and authenticated/API-keyed, same check that gates
    whether a session can run with it at all). Falls back to Claude
    (the template's own implicit default, left unset) if the
    recommendation isn't connected, rather than silently pointing a
    fresh agent at a provider that would just fail to run."""
    written = []
    for agent_id in agent_ids:
        parsed = _read_template(_template_path(agent_id))
        if parsed is None:
            continue
        frontmatter, body = parsed
        frontmatter, body = attach_default_skills(agent_id, frontmatter, body)
        recommended = recommended_provider(agent_id)
        if recommended != "claude" and providers.usable(recommended):
            frontmatter["primary_provider"] = recommended
        filename = f"{agent_id}.md"
        agents_store.write_agent(filename, frontmatter, body, agents_dir=agents_dir)
        written.append(filename)

    if "project-scribe.md" in written and agents_dir is not None:
        root = agent_formats.root_for_agents_dir(agents_dir)
        if root != Path.home():  # global stack has no real project directory to nudge
            ensure_continuity_nudge(root)

    return written


def activate_preset(preset_id: str, agents_dir: Path | None = None) -> list[str]:
    for preset in list_presets():
        if preset["id"] == preset_id:
            return activate(preset["agents"], agents_dir=agents_dir)
    raise ValueError(f"Unknown preset: {preset_id}")
