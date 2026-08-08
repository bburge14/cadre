"""Registry of supported AI CLI providers -- what binary to run, how to
start a fresh session vs resume one, and whether/how API-key auth works.

Claude uses its own account login (already required just to run this app
at all). Gemini/Codex/Kimi are API-key-only here -- their account-login
flows are baked into each CLI binary itself (each ships its own
pre-registered OAuth client), so there's no equivalent of the GitHub/GitLab
OAuth flow a third-party app can implement directly; the only way to
trigger it is running the CLI interactively, which produced a confusing
"this looks like it started a whole session" UX for what should be a
one-off login action. Simpler and clearer: API keys only for these three.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import settings


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    binary: str
    supports_upfront_session_id: bool
    api_key_env_var: str | None
    remote_control: bool  # has an official Claude-Code-style remote control
    supports_orchestration: bool  # can this provider run an Agent Stack (coordinator + subagents)?
    orchestration_verified: bool  # has that actually been confirmed against a real running install, not just schema docs
    install_hint: str  # exact command to install this CLI, confirmed against its official docs/npm page
    install_docs_url: str
    # (value, label) pairs for this provider's own native model catalog --
    # empty means "no catalog wired up yet, agents stay on that CLI's own
    # default." Deliberately NOT a cross-vendor mapping: Claude's list
    # lives in the agent's existing `model` frontmatter key (unchanged,
    # pre-existing field); every other provider gets its own dedicated
    # `<provider_id>_model` key instead (see agent_formats.py), since
    # model names aren't equivalent across vendors by string -- writing
    # Claude's "opus" into a Gemini or Codex config would be meaningless
    # to that CLI. Sourced 2026-08 (see providers.py's own research
    # notes below each list); Codex/Kimi intentionally left empty for
    # now -- Codex's docs conflict with themselves on accepted
    # model_reasoning_effort values and GitHub issues #14671/#15250
    # report the schema isn't reliably honored at runtime yet; Kimi
    # Code's native format has no free-text model field at all, only a
    # system-wide `model_preference: primary|secondary` toggle in
    # config.toml -- not something this per-agent dropdown pattern can
    # honestly represent without misleading the user into thinking it's
    # per-agent when it's actually global.
    models: tuple[tuple[str, str], ...] = ()

    def new_session_args(self, session_id: str, label: str, unattended: bool = False) -> list[str]:
        if self.id == "claude":
            args = [self.binary, "--session-id", session_id, "--remote-control", label]
            return self._add_unattended(args, unattended)
        if self.id == "kimi":
            return [self.binary, "--session", session_id]
        # Gemini/Codex: no confirmed way to choose a new session's ID
        # upfront (see plan's Known Unknowns) -- start fresh and let the
        # caller discover the real ID afterward via session_id_after_spawn.
        return [self.binary]

    def resume_args(self, session_id: str, label: str, unattended: bool = False) -> list[str]:
        if self.id == "claude":
            args = [self.binary, "--resume", session_id, "--remote-control", label]
            return self._add_unattended(args, unattended)
        if self.id == "gemini":
            return [self.binary, "--resume", session_id]
        if self.id == "codex":
            return [self.binary, "resume", session_id]
        if self.id == "kimi":
            return [self.binary, "--session", session_id]
        raise ValueError(f"Unknown provider: {self.id}")

    def _add_unattended(self, args: list[str], unattended: bool) -> list[str]:
        # Lets a workflow run finish a task with nobody there to approve
        # each step -- opt-in only (see workflows_store.py), since this
        # disables every permission prompt Claude Code would otherwise
        # show for file edits/bash commands. Claude-only for now: no
        # verified equivalent flag exists yet for Gemini/Codex/Kimi
        # (matches this file's existing orchestration_verified=False
        # honesty pattern) -- the workflow UI only offers the "run
        # unattended" checkbox for Claude-provider workflows until one is.
        if unattended and self.id == "claude":
            return [*args, "--dangerously-skip-permissions"]
        return args

    def consult_command_hint(self) -> str:
        """The exact non-interactive single-prompt invocation, for embedding
        in a subagent's own instructions -- confirmed by direct testing on
        this machine (auth-only failures, syntax verified correct):
        `gemini -p "..."`, `codex exec "..."`, `kimi -p "..."`."""
        if self.id == "gemini":
            return f'{self.binary} -p "<your fully-specified question or task>"'
        if self.id == "codex":
            return f'{self.binary} exec "<your fully-specified question or task>"'
        if self.id == "kimi":
            return f'{self.binary} -p "<your fully-specified question or task>"'
        raise ValueError(f"{self.id} has no non-interactive consult mode")


PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        id="claude", label="Claude", binary="claude",
        supports_upfront_session_id=True, api_key_env_var=None,
        remote_control=True, supports_orchestration=True, orchestration_verified=True,
        install_hint="npm install -g @anthropic-ai/claude-code",
        install_docs_url="https://docs.claude.com/en/docs/claude-code/setup",
        models=(
            ("inherit", "Inherit (session default)"),
            ("haiku", "Haiku — fastest/cheapest"),
            ("sonnet", "Sonnet — balanced"),
            ("opus", "Opus — most capable"),
            ("fable", "Fable"),
        ),
    ),
    "gemini": Provider(
        id="gemini", label="Gemini", binary="gemini",
        supports_upfront_session_id=False, api_key_env_var="GEMINI_API_KEY",
        remote_control=False, supports_orchestration=True, orchestration_verified=False,
        install_hint="npm install -g @google/gemini-cli",
        install_docs_url="https://geminicli.com/docs/get-started/installation/",
        # Sourced 2026-08 from geminicli.com/docs/core/subagents/ (confirms
        # the subagent frontmatter's own `model:` key, full model ID
        # string, omitted = inherit) and geminicli.com/docs/cli/model/ +
        # ai.google.dev/gemini-api/docs/pricing (model list + tiering).
        # Flagged, unresolved conflict: the model-picker docs page lists
        # the Pro-tier Gemini 3 model as "gemini-3-pro-preview"; Google's
        # own pricing page instead lists "gemini-3.1-pro-preview" with no
        # "gemini-3-pro-preview" entry at all. Went with the model-picker
        # page's string here since it's the more directly relevant source
        # (what the CLI's own /model command actually lists), but this
        # needs a live check against an installed `gemini` binary before
        # anyone should trust it blindly.
        models=(
            ("", "Inherit (session default)"),
            ("gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite — cheapest"),
            ("gemini-2.5-flash", "Gemini 2.5 Flash — fast"),
            ("gemini-3-flash-preview", "Gemini 3 Flash — fast"),
            ("gemini-2.5-pro", "Gemini 2.5 Pro — capable"),
            ("gemini-3-pro-preview", "Gemini 3 Pro — most capable (unverified ID, see comment above)"),
        ),
    ),
    "codex": Provider(
        id="codex", label="Codex", binary="codex",
        supports_upfront_session_id=False, api_key_env_var="OPENAI_API_KEY",
        remote_control=False, supports_orchestration=True, orchestration_verified=False,
        install_hint="npm install -g @openai/codex",
        install_docs_url="https://github.com/openai/codex",
    ),
    "kimi": Provider(
        id="kimi", label="Kimi", binary="kimi",
        supports_upfront_session_id=True, api_key_env_var="MOONSHOT_API_KEY",
        remote_control=False, supports_orchestration=True, orchestration_verified=False,
        install_hint="npm install -g @moonshot-ai/kimi-code",
        install_docs_url="https://github.com/MoonshotAI/kimi-code",
    ),
}


def get(provider_id: str) -> Provider:
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    return PROVIDERS[provider_id]


def list_providers() -> list[Provider]:
    return list(PROVIDERS.values())


def binary_found(provider_id: str) -> bool:
    """Whether the provider's CLI is even installed and on PATH -- distinct
    from being logged in. A missing binary means every session spawn for
    that provider will fail immediately, before auth ever matters."""
    return shutil.which(get(provider_id).binary) is not None


def claude_logged_in() -> bool:
    """Heuristic only: the claude CLI writes its cached account credentials
    here after `/login` succeeds. Presence isn't a live validity check (the
    token could be expired/revoked), just "you've logged in before"."""
    return (Path.home() / ".claude" / ".credentials.json").exists()


def usable(provider_id: str) -> bool:
    """Whether this provider is actually connected and ready to spawn a
    session right now -- binary on PATH, plus Claude's account login or
    the other providers' API key."""
    provider = get(provider_id)
    if not binary_found(provider_id):
        return False
    if provider_id == "claude":
        return claude_logged_in()
    return bool(settings.get(f"{provider_id}_api_key"))


def orchestration_candidates() -> list[Provider]:
    """Providers eligible to be picked as the default/orchestrator --
    connected right now AND capable of running an Agent Stack at all.
    Today that's Claude only: Agent Stacks are Claude Code's own native
    subagent mechanism (it's the one binary that reads .claude/agents/),
    so a session running Gemini/Codex/Kimi has no orchestrator to hand a
    stack to no matter how well-connected it is. supports_orchestration
    exists as its own flag (not folded into usable()) so a future provider
    that gains an equivalent mechanism only needs that one field flipped."""
    return [p for p in PROVIDERS.values() if p.supports_orchestration and usable(p.id)]
