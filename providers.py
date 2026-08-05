"""Registry of supported AI CLI providers -- what binary to run, how to
start a fresh session vs resume one, and whether/how API-key auth works.

Login (account-based auth) is NOT handled here: each CLI manages its own
OS-level credential cache the same way `claude`/`/login` already does.
This module only needs to know how to *invoke* each one; login itself is
just running that binary interactively (see session_daemon.py's login
support), same mechanism as any other session.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    binary: str
    supports_upfront_session_id: bool
    api_key_env_var: str | None
    remote_control: bool  # has an official Claude-Code-style remote control

    def new_session_args(self, session_id: str, label: str) -> list[str]:
        if self.id == "claude":
            return [self.binary, "--session-id", session_id, "--remote-control", label]
        if self.id == "kimi":
            return [self.binary, "--session", session_id]
        # Gemini/Codex: no confirmed way to choose a new session's ID
        # upfront (see plan's Known Unknowns) -- start fresh and let the
        # caller discover the real ID afterward via session_id_after_spawn.
        return [self.binary]

    def resume_args(self, session_id: str, label: str) -> list[str]:
        if self.id == "claude":
            return [self.binary, "--resume", session_id, "--remote-control", label]
        if self.id == "gemini":
            return [self.binary, "--resume", session_id]
        if self.id == "codex":
            return [self.binary, "resume", session_id]
        if self.id == "kimi":
            return [self.binary, "--session", session_id]
        raise ValueError(f"Unknown provider: {self.id}")

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

    def login_args(self) -> list[str]:
        # Triggers each CLI's own first-run/`/login`-equivalent flow.
        # Confirmed for Kimi (device-code flow on bare invocation); Gemini
        # and Codex's exact standalone login command is an open question
        # (see plan) -- bare invocation is the safe default, since all
        # known agentic CLIs prompt for auth on first use if not already
        # logged in.
        return [self.binary]


PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        id="claude", label="Claude", binary="claude",
        supports_upfront_session_id=True, api_key_env_var=None,
        remote_control=True,
    ),
    "gemini": Provider(
        id="gemini", label="Gemini", binary="gemini",
        supports_upfront_session_id=False, api_key_env_var="GEMINI_API_KEY",
        remote_control=False,
    ),
    "codex": Provider(
        id="codex", label="Codex", binary="codex",
        supports_upfront_session_id=False, api_key_env_var="OPENAI_API_KEY",
        remote_control=False,
    ),
    "kimi": Provider(
        id="kimi", label="Kimi", binary="kimi",
        supports_upfront_session_id=True, api_key_env_var="MOONSHOT_API_KEY",
        remote_control=False,
    ),
}


def get(provider_id: str) -> Provider:
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id}")
    return PROVIDERS[provider_id]


def list_providers() -> list[Provider]:
    return list(PROVIDERS.values())
