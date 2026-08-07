"""Applies your chosen terminal theme (dark/light/auto, plus several
named palettes -- see _THEME_NAMES) to a new session's provider
automatically -- all four CLIs support pre-launch,
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

# Per provider: this app's own theme name mapped to that CLI's own
# literal config value. None means "don't write anything" -- for "auto"
# specifically, that's often the *correct* way to ask a provider for
# auto-detection (see codex below), not a gap. Everything past dark/
# light/auto is a *named* palette Cadre's own xterm.js view fully
# renders itself (see XTERM_THEMES in static/terminal.js) -- the native
# mapping below is a best-effort match onto each CLI's own catalog for
# anyone using that CLI's native Remote Control outside this dashboard,
# not something this app depends on for its own rendering. Where a
# provider has no equivalent built-in theme, None leaves its config
# alone rather than forcing something that doesn't actually match.
_THEME_NAMES: dict[str, dict[str, str | None]] = {
    # docs.claude.com/en/docs/claude-code/terminal-config + the installed
    # CLI's own string table (v2.1.223) -- 6 base presets plus "auto", no
    # named/branded themes beyond dark/light and their daltonized/ansi
    # variants, so every named palette below just picks whichever of
    # those 6 is the closer dark/light match.
    "claude": {
        "dark": "dark", "light": "light", "auto": "auto",
        "dracula": "dark", "solarized-dark": "dark", "solarized-light": "light",
        "nord": "dark", "monokai": "dark", "gruvbox-dark": "dark",
        "tokyo-night": "dark", "one-dark": "dark",
        "catppuccin-mocha": "dark", "synthwave": "dark", "matrix": "dark",
        "ayu-dark": "dark", "github-dark": "dark", "cyberpunk": "dark",
        "rose-quartz": "dark", "deep-forest": "dark", "abyssal": "dark",
        "sunset-blvd": "dark", "arctic-frost": "dark", "blood-moon-term": "dark",
    },
    # google-gemini/gemini-cli packages/cli/src/ui/themes/theme-manager.ts
    # (verified against the installed @google/gemini-cli package) -- built-in
    # themes use branded names, not generic "dark"/"light" strings; no "auto"
    # value exists at all (open feature request, gemini-cli#18507). Several
    # named palettes below have an exact match in Gemini's own 19-theme
    # catalog; the rest (Nord/Monokai/Gruvbox -- not in that catalog) fall
    # back to None rather than forcing an unrelated theme.
    "gemini": {
        "dark": "Default", "light": "Default Light", "auto": None,
        "dracula": "Dracula", "solarized-dark": "Solarized Dark", "solarized-light": "Solarized Light",
        "nord": None, "monokai": None, "gruvbox-dark": None,
        "tokyo-night": "Tokyo Night", "one-dark": "Atom One",
        "catppuccin-mocha": None, "synthwave": None, "matrix": None,
        "ayu-dark": "Ayu", "github-dark": "GitHub", "cyberpunk": None,
        # These six are Cadre's own original palettes (see terminal.js),
        # not reproductions of a named catalog entry -- no verified match
        # to force, same as Nord/Monokai/Gruvbox above.
        "rose-quartz": None, "deep-forest": None, "abyssal": None,
        "sunset-blvd": None, "arctic-frost": None, "blood-moon-term": None,
    },
    # openai/codex codex-rs/tui/src/render/highlight.rs, verified against
    # the exact source tag matching the installed @openai/codex build --
    # parse_theme_name()'s match arms are the real catalog (31 themes, far
    # more than just the two auto-detection picks below). Omitting tui.theme
    # entirely triggers Codex's own terminal-background auto-detection (its
    # literal meaning of "auto"), so auto=None is correct, not unimplemented
    # -- catppuccin-mocha/latte are what that auto-detection would pick
    # anyway. one-dark has no exact match; one-half-dark is the closest
    # relative in Codex's own catalog.
    "codex": {
        "dark": "catppuccin-mocha", "light": "catppuccin-latte", "auto": None,
        "dracula": "dracula", "solarized-dark": "solarized-dark", "solarized-light": "solarized-light",
        "nord": "nord", "monokai": "monokai-extended", "gruvbox-dark": "gruvbox-dark",
        "tokyo-night": None, "one-dark": "one-half-dark",
        "catppuccin-mocha": "catppuccin-mocha", "synthwave": None, "matrix": None,
        "ayu-dark": None, "github-dark": "github", "cyberpunk": "dark-neon",
        # Same reasoning as gemini's None entries above -- these six are
        # Cadre's own original palettes, no real catalog match to claim.
        "rose-quartz": None, "deep-forest": None, "abyssal": None,
        "sunset-blvd": None, "arctic-frost": None, "blood-moon-term": None,
    },
    # `kimi` is two unrelated MoonshotAI projects that collide on the same
    # command name depending on pip vs npm install (MoonshotAI/kimi-cli,
    # Python, vs MoonshotAI/kimi-code, TypeScript) -- apply_theme() writes
    # both targets since there's no way to know which one a given install
    # actually is. Their theme support genuinely differs: kimi-code supports
    # dark/light/auto plus arbitrary custom theme files (none of the named
    # palettes below have a bundled match, so they fall back to dark/light);
    # kimi-cli (src/kimi_cli/config.py) only accepts literally "dark" or
    # "light" -- no "auto" at all -- so this table intentionally has no
    # "auto" entry for kimi and apply_theme() maps it per-target instead of
    # sharing one value the way the other three providers can.
    "kimi": {
        "dark": "dark", "light": "light",
        "dracula": "dark", "solarized-dark": "dark", "solarized-light": "light",
        "nord": "dark", "monokai": "dark", "gruvbox-dark": "dark",
        "tokyo-night": "dark", "one-dark": "dark",
        "catppuccin-mocha": "dark", "synthwave": "dark", "matrix": "dark",
        "ayu-dark": "dark", "github-dark": "dark", "cyberpunk": "dark",
        "rose-quartz": "dark", "deep-forest": "dark", "abyssal": "dark",
        "sunset-blvd": "dark", "arctic-frost": "dark", "blood-moon-term": "dark",
    },
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
    session is about to start in. theme is one of the names in
    _THEME_NAMES (dark/light/auto plus the named palettes)."""
    root = Path(workdir)

    if provider_id == "kimi":
        # kimi-code (tui.toml) supports "auto" and defaults to it; kimi-cli
        # (config.toml) has no "auto" concept at all (Literal["dark","light"]
        # in its own Pydantic model) -- writing "auto" there would be a
        # value its own config loader rejects. Resolved per-target instead
        # of through the shared _THEME_NAMES lookup below, which has no
        # single value that's correct for both.
        code_value = "auto" if theme == "auto" else _THEME_NAMES["kimi"].get(theme)
        cli_value = "dark" if theme == "auto" else _THEME_NAMES["kimi"].get(theme)
        if code_value:
            _ensure_toml_theme(Path.home() / ".kimi-code" / "tui.toml", code_value, table=None)
        if cli_value:
            _ensure_toml_theme(Path.home() / ".kimi" / "config.toml", cli_value, table=None)
        return

    mapped = _THEME_NAMES.get(provider_id, {}).get(theme)
    if not mapped:
        return

    if provider_id == "claude":
        _merge_json_key(root / ".claude" / "settings.json", ["theme"], mapped)
    elif provider_id == "gemini":
        _merge_json_key(root / ".gemini" / "settings.json", ["ui", "theme"], mapped)
    elif provider_id == "codex":
        _ensure_toml_theme(root / ".codex" / "config.toml", mapped, table="tui")
