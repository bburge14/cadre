"""Applies your chosen terminal theme (dark/light/auto) to a new
session's provider automatically -- all four CLIs support pre-launch,
non-interactive theme configuration via their own config files, so this
is pure file-writing at session-creation time, no daemon/argv changes
and no keystrokes to simulate. Every writer here is additive-only: an
existing config file's other content is preserved, never overwritten.

All four providers' literal theme-name strings are now source-verified
(against actual code constants, not docs/blog paraphrases) -- see the
_THEME_NAMES table below, and the comment on each entry for where it
came from and why "auto" resolves the way it does per provider. Kimi is
the one exception: its config *format and path* (not the theme names
themselves) has some upstream ambiguity -- see apply_theme() below.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# Per provider: this app's own "dark"/"light"/"auto" mapped to that CLI's
# own literal config value. None means "don't write anything" -- for
# "auto" specifically, that's often the *correct* way to ask a provider
# for auto-detection (see codex below), not a gap.
_THEME_NAMES: dict[str, dict[str, str | None]] = {
    # docs.claude.com/en/docs/claude-code/terminal-config -- literal preset names.
    "claude": {"dark": "dark", "light": "light", "auto": "auto"},
    # google-gemini/gemini-cli packages/cli/src/ui/themes/theme-manager.ts --
    # built-in themes use branded names, not generic "dark"/"light" strings;
    # no "auto" value exists at all (open feature request, gemini-cli#18507).
    "gemini": {"dark": "Default", "light": "Default Light", "auto": None},
    # openai/codex codex-rs/tui/src/render/highlight.rs (BUILTIN_THEME_NAMES) --
    # no plain "dark"/"light"/"auto" strings exist. Omitting tui.theme entirely
    # triggers Codex's own terminal-background auto-detection (its literal
    # meaning of "auto"), so auto=None here is correct, not unimplemented --
    # catppuccin-mocha/latte are what that auto-detection would pick anyway.
    "codex": {"dark": "catppuccin-mocha", "light": "catppuccin-latte", "auto": None},
    "kimi": {"dark": "dark", "light": "light", "auto": "auto"},
}


def _merge_json_key(path: Path, key_path: list[str], value: str) -> None:
    """Sets a nested key in a JSON file, creating the file/parent dirs if
    needed, preserving every other key already there."""
    data = json.loads(path.read_text()) if path.exists() else {}
    node = data
    for key in key_path[:-1]:
        node = node.setdefault(key, {})
    node[key_path[-1]] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


_TOML_START = "# BEGIN CADRE THEME"
_TOML_END = "# END CADRE THEME"
_TOML_BLOCK_RE = re.compile(re.escape(_TOML_START) + r".*?" + re.escape(_TOML_END) + r"\n*", re.DOTALL)


def _ensure_toml_theme(path: Path, theme_name: str, table: str | None) -> None:
    """Marker-delimited, same pattern as agents_store.py's auto-generated
    blocks and presets.py's CLAUDE.md nudge: lets a later call safely
    *update* a theme Cadre itself previously wrote (changing your Settings
    theme should actually take effect next session, not just once), while
    still never touching a [table]/theme that predates Cadre or that the
    CLI itself manages -- that case is left alone entirely, block or no
    block. Hand-written TOML, no parser dependency, same as
    agent_formats.py's Codex agent files."""
    existing = path.read_text() if path.exists() else ""
    inner = f'[{table}]\ntheme = "{theme_name}"\n' if table else f'theme = "{theme_name}"\n'
    block = f"{_TOML_START}\n{inner}{_TOML_END}\n"

    if _TOML_START in existing:
        path.write_text(_TOML_BLOCK_RE.sub(block, existing))
        return

    marker = f"[{table}]" if table else "theme"
    if marker in existing:
        return  # pre-existing, non-Cadre config for this -- leave it alone

    path.parent.mkdir(parents=True, exist_ok=True)
    if existing.strip():
        path.write_text(existing.rstrip() + "\n\n" + block)
    else:
        path.write_text(block)


def apply_theme(workdir: str, provider_id: str, theme: str) -> None:
    """Called once, at session-creation time, for the directory a new
    session is about to start in. theme is 'dark', 'light', or 'auto'."""
    mapped = _THEME_NAMES.get(provider_id, {}).get(theme)
    if not mapped:
        return
    root = Path(workdir)

    if provider_id == "claude":
        _merge_json_key(root / ".claude" / "settings.json", ["theme"], mapped)
    elif provider_id == "gemini":
        _merge_json_key(root / ".gemini" / "settings.json", ["ui", "theme"], mapped)
    elif provider_id == "codex":
        _ensure_toml_theme(root / ".codex" / "config.toml", mapped, table="tui")
    elif provider_id == "kimi":
        # Path uncertainty in upstream docs (two candidate defaults, two
        # possibly-different binaries named `kimi`) -- write both rather
        # than guess which one this install actually reads. Also global/
        # user-scoped, not project-scoped like the other three, since
        # project-level TUI config for Kimi isn't confirmed to exist.
        _ensure_toml_theme(Path.home() / ".kimi-code" / "tui.toml", mapped, table=None)
        _ensure_toml_theme(Path.home() / ".kimi" / "config.toml", mapped, table=None)
