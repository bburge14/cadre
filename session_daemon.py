"""Long-running process that owns every session's pty and subprocess.

Deliberately kept separate from app.py: the whole point is that a session's
aliveness depends on this process staying up (its pty must stay open and
read from), so restarting/redeploying the *web app* must never be what
kills a live session. This process should only need restarting for its own
bug fixes, which are rare -- routine app.py/template/auth changes never
touch it.

Talks to app.py over a TCP loopback socket (127.0.0.1 only) rather than a
Unix domain socket, since AF_UNIX support on Windows is inconsistent --
this way the exact same code runs on Linux, macOS, and Windows.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import socketserver
import sys
import threading
import time
import uuid as uuid_mod
from collections import deque
from datetime import datetime
from pathlib import Path

import croniter
import websockets
import websockets.exceptions

import config
import integrations_store
import providers
import pty_compat
import sessions_store
import settings
import stacks_store
import workflows_store

_TOKEN_TTL_SECONDS = 60
_terminal_tokens: dict[str, tuple[str, float]] = {}
_ws_loop: asyncio.AbstractEventLoop | None = None

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ANSI_OTHER_RE = re.compile(r"\x1b[^\[]")

# Auto-confirm patterns for each provider's first-run trust/consent prompt,
# matched the same way as Claude's (ANSI-stripped, whitespace-collapsed,
# since cursor-positioning escapes remove literal spaces from prompt text).
# Only Claude's is confirmed by direct testing; Gemini/Codex/Kimi may have
# an equivalent first-run prompt with different wording that isn't handled
# yet -- expect to add entries here once seen on real hardware.
TRUST_PROMPT_PATTERNS: dict[str, str] = {
    "claude": "trustthisfolder",
}

# The one-time warning Claude Code shows *only* when launched with
# --dangerously-skip-permissions (i.e. only for unattended=True workflow
# runs) -- confirmed via live testing 2026-08-08 that this is a separate
# prompt from TRUST_PROMPT_PATTERNS above, not a variant of it, and that
# without handling it a workflow's readiness poll times out after
# _WORKFLOW_READY_TIMEOUT with the session just sitting here forever.
# Its options have the OPPOSITE polarity from the trust-folder prompt --
# "1. No, exit" / "2. Yes, I accept" -- so this needs its own "2\r"
# response, not the trust-prompt's "1\r".
UNATTENDED_WARNING_PATTERNS: dict[str, str] = {
    "claude": "bypasspermissionsmode",
}

# Substrings (ANSI-stripped, whitespace-collapsed, lowercased -- same
# normalization as the trust-prompt check) that mean a provider has hit a
# usage/rate/context limit and stopped responding on its own. Claude's
# wording ("usage limit reached", "5-hour limit") is confirmed by direct
# observation; the rest are generic API-error phrasings likely to show up
# across Gemini/Codex/Kimi regardless of exact CLI wording, since none of
# those three has been seen hitting a real limit on this machine yet.
LIMIT_PATTERNS: list[str] = [
    "usagelimitreached",
    "limitreached",
    "5-hourlimit",
    "weeklylimit",
    "ratelimit",
    "429toomanyrequests",
    "quotaexceeded",
    "resourceexhausted",
    "insufficientquota",
    "contextlow",
    "contextwindowexceeded",
]

# A cap on total *characters* of raw backlog kept per session, not just
# item count -- the previous deque(maxlen=2000) capped how many
# splitlines() fragments were kept, but a rich TUI's own live status-bar
# redraws (cursor-positioning + overwrite, not real newlines) produce a
# huge number of tiny fragments, so 2000 of them could still add up to
# ~150KB+ of raw bytes spanning a long time window. Replaying backlog
# that old into a terminal connecting at a *different* column width than
# whatever was active when those bytes were originally written garbles
# outright -- cursor-positioning escapes captured for one width don't
# mean anything at another, and there's no reliable "full screen clear"
# marker in this kind of output to safely resync from (confirmed: this
# CLI's redraws use cursor-home + overwrite, never an actual clear-
# screen sequence). A real fix needs a server-side virtual terminal
# tracking actual screen-cell state so it can re-render at any width on
# demand (the way tmux/screen do) -- out of scope here. Capping by
# character count instead bounds *how much* stale, possibly-wrong-width
# content a new connection can ever be handed, which doesn't eliminate
# the problem but meaningfully shrinks its blast radius and window.
MAX_BACKLOG_CHARS = 60_000

_lock = threading.Lock()
_runtime: dict[str, dict] = {}


def _mark_ready(session_id: str) -> None:
    with _lock:
        rt = _runtime.get(session_id)
        if rt is not None:
            rt["ready"] = True


def _schedule_ready(session_id: str) -> None:
    # A short settle delay past "trust prompt handled" (or past spawn, for
    # a provider with no trust prompt at all) -- rt["ready"] is what a
    # workflow run (session_daemon.py's _run_workflow) waits on before
    # writing a prompt into a freshly spawned session; writing the instant
    # the trust prompt clears risks landing before the CLI's own startup
    # rendering (welcome banner, prompt box) has actually finished.
    threading.Timer(1.5, _mark_ready, args=(session_id,)).start()


# Safety-net upper bound for "no prompt is coming at all" -- confirmed via
# live testing 2026-08-08 that Claude Code remembers having already
# trusted a directory and already accepted the bypass-permissions warning
# on a per-project basis, and simply never shows either prompt again on a
# later run. Detection-only readiness (only ever marking ready *after*
# seeing a pattern) can't handle that: if the prompt never appears, it
# never fires, and every workflow run against an already-trusted directory
# would time out and error forever. This fallback timer guarantees ready
# eventually gets set either way; it's generous (well past the ~1-2s
# observed for a prompt to actually render) so it only ever matters for
# the "prompt was skipped" case, not the normal "respond to it" case,
# which still completes via the much faster _schedule_ready path below.
_READY_FALLBACK_SECONDS = 8


def _reader(
    session_id: str, pty_session: pty_compat.PtySession, provider_id: str, unattended: bool = False,
) -> None:
    trust_pattern = TRUST_PROMPT_PATTERNS.get(provider_id)
    trust_check_buffer = ""
    trust_handled = trust_pattern is None

    bypass_pattern = UNATTENDED_WARNING_PATTERNS.get(provider_id) if unattended else None
    bypass_check_buffer = ""
    bypass_handled = bypass_pattern is None

    ready_scheduled = False
    fallback_timer = threading.Timer(_READY_FALLBACK_SECONDS, _mark_ready, args=(session_id,))
    fallback_timer.start()

    def _maybe_schedule_ready() -> None:
        nonlocal ready_scheduled
        if trust_handled and bypass_handled and not ready_scheduled:
            ready_scheduled = True
            fallback_timer.cancel()
            _schedule_ready(session_id)

    _maybe_schedule_ready()
    limit_check_buffer = ""
    limit_already_flagged = False
    while True:
        chunk = pty_session.read(4096)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        with _lock:
            rt = _runtime.get(session_id)
            if rt is None:
                break
            for line in text.splitlines(keepends=True):
                rt["output"].append(line)
                rt["output_chars"] += len(line)
            while rt["output_chars"] > MAX_BACKLOG_CHARS and rt["output"]:
                rt["output_chars"] -= len(rt["output"].popleft())
            subscribers = list(rt["subscribers"])
        # Fan out live bytes to any open terminal websockets for this
        # session. This is the *only* place that reads pty_session -- a
        # websocket handler never reads the pty directly, since two
        # independent readers on the same fd would split/lose bytes
        # unpredictably. call_soon_threadsafe because this thread isn't
        # the asyncio event loop the subscriber queues belong to.
        if subscribers and _ws_loop is not None:
            for queue in subscribers:
                _ws_loop.call_soon_threadsafe(queue.put_nowait, text)

        if not trust_handled:
            trust_check_buffer += text
            plain = _ANSI_CSI_RE.sub("", trust_check_buffer)
            plain = _ANSI_OTHER_RE.sub("", plain)
            plain_nospace = re.sub(r"\s+", "", plain).lower()
            if trust_pattern in plain_nospace:
                pty_session.write(b"1\r")
                trust_handled = True
                _maybe_schedule_ready()
            elif len(trust_check_buffer) > 20000:
                trust_check_buffer = trust_check_buffer[-5000:]

        if not bypass_handled:
            bypass_check_buffer += text
            plain = _ANSI_CSI_RE.sub("", bypass_check_buffer)
            plain = _ANSI_OTHER_RE.sub("", plain)
            plain_nospace = re.sub(r"\s+", "", plain).lower()
            if bypass_pattern in plain_nospace:
                pty_session.write(b"2\r")
                bypass_handled = True
                _maybe_schedule_ready()
            elif len(bypass_check_buffer) > 20000:
                bypass_check_buffer = bypass_check_buffer[-5000:]

        if not limit_already_flagged:
            limit_check_buffer += text
            plain = _ANSI_CSI_RE.sub("", limit_check_buffer)
            plain = _ANSI_OTHER_RE.sub("", plain)
            plain_nospace = re.sub(r"\s+", "", plain).lower()
            hit = next((p for p in LIMIT_PATTERNS if p in plain_nospace), None)
            if hit is not None:
                limit_already_flagged = True
                message = " ".join(plain.split())[-300:]
                with _lock:
                    rt = _runtime.get(session_id)
                    if rt is not None:
                        rt["limit_hit"] = True
                        rt["limit_message"] = message or hit
            elif len(limit_check_buffer) > 20000:
                limit_check_buffer = limit_check_buffer[-5000:]


def status(session_id: str) -> dict:
    with _lock:
        rt = _runtime.get(session_id)
        own_running = rt is not None and rt["pty"].is_alive()
        own_pid = rt["pty"].pid if rt else None
        pid = own_pid if own_running else None
        limit_hit = bool(rt["limit_hit"]) if rt else False
        limit_message = rt["limit_message"] if rt else None
    externally_managed = False
    if not own_running:
        externals = pty_compat.find_pids_by_arg(session_id, own_pid)
        if externals:
            own_running = True
            pid = externals[0]
            externally_managed = True
    return {
        "running": own_running,
        "pid": pid,
        "externally_managed": externally_managed,
        "limit_hit": limit_hit,
        "limit_message": limit_message,
    }


def get_output(session_id: str, max_chars: int = 8000) -> str:
    with _lock:
        rt = _runtime.get(session_id)
        if rt is None:
            return ""
        text = "".join(rt["output"])
    text = _ANSI_CSI_RE.sub("", text)
    text = _ANSI_OTHER_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[-max_chars:]


def write(session_id: str, text: str) -> dict:
    """Sends text into a running session's pty as if a human had typed it
    and pressed Enter. This is what lets a workflow run actually deliver
    its prompt.

    The text and the Enter keystroke are two separate pty writes with a
    short gap between them, not one combined "text\r" write -- confirmed
    via live testing 2026-08-08 that Claude Code's chat input runs under
    bracketed paste mode, which buffers a burst of input as a paste and
    swallows a \r embedded in the same write instead of treating it as
    Enter. The text lands in the input box either way; without the split,
    it just sits there unsubmitted forever. (The trust-prompt and
    bypass-permissions-warning auto-confirms in _reader don't need this --
    those are raw selection menus that appear before bracketed paste mode
    is active, and a single combined write works fine there.)"""
    with _lock:
        rt = _runtime.get(session_id)
        if rt is None or not rt["pty"].is_alive():
            return {"ok": False, "error": "session not running"}
        rt["pty"].write(text.encode("utf-8"))
    time.sleep(0.15)
    with _lock:
        rt = _runtime.get(session_id)
        if rt is None or not rt["pty"].is_alive():
            return {"ok": False, "error": "session not running"}
        rt["pty"].write(b"\r")
    return {"ok": True}


# claude.ai's Gmail/Calendar/Drive connectors (see providers.py's docs
# references -- these are Anthropic-hosted, tied to the logged-in Claude
# account, confirmed via direct testing 2026-08-08) have no scriptable
# API of their own for connecting one: the only way is Claude Code's own
# interactive `/mcp` picker, an arrow-key-driven menu with no shareable
# link to skip straight to.
#
# Originally attempted to fully script that picker (find the row, expand
# "unused connectors", select, confirm) server-side. Abandoned after
# extensive live testing 2026-08-08: hand-written raw arrow-key bytes
# (\x1b[B) didn't reliably land as actual navigation in this specific
# menu -- get_output()'s ANSI-stripping also collapses this screen's
# cursor-positioning enough that reliably locating "the current selected
# row" from the stripped text alone wasn't achievable without a real
# server-side terminal emulator (out of scope, see MAX_BACKLOG_CHARS'
# comment above for the same conclusion elsewhere in this file).
#
# What this does instead, and is fully reliable: spawn/reuse the
# connector session, wait for it to actually be ready for input (skipping
# this on a brand-new session sends /mcp into whatever trust-prompt
# screen is still showing -- confirmed via live testing), and run /mcp.
# That's real progress over the status quo -- it gets the user to the
# menu with zero terminal knowledge needed -- the last few keystrokes
# (down/Enter through an obvious, self-explanatory menu) happen in a
# real embedded terminal instead of guessed-at automation.
def start_mcp_connector_session(session_id: str) -> dict:
    deadline = time.time() + _WORKFLOW_READY_TIMEOUT
    while time.time() < deadline:
        with _lock:
            rt = _runtime.get(session_id)
            if rt is not None and rt.get("ready"):
                break
        time.sleep(0.5)
    else:
        return {"ok": False, "error": "session never became ready for input"}
    if not write(session_id, "/mcp").get("ok"):
        return {"ok": False, "error": "session not running"}
    return {"ok": True}


_mcp_connector_session_results: dict[str, dict] = {}


def _start_mcp_connector_session_impl(session_id: str) -> None:
    result = start_mcp_connector_session(session_id)
    with _lock:
        _mcp_connector_session_results[session_id] = result


def start_mcp_connector_session_async(session_id: str) -> dict:
    threading.Thread(target=_start_mcp_connector_session_impl, args=(session_id,), daemon=True).start()
    return {"ok": True, "started": True}


def get_mcp_connector_session_result(session_id: str) -> dict:
    with _lock:
        result = _mcp_connector_session_results.pop(session_id, None)
    if result is None:
        return {"ok": True, "pending": True}
    return {"ok": True, "pending": False, "result": result}


def _stack_integration_env(workdir: str) -> dict:
    """Env vars for whichever integrations the stack rooted at this
    directory has opted into (see integrations_store.py + stack_form.html's
    checklist) -- matched by exact workdir string, the same way every
    other workdir-to-stack lookup in this app already works. No match
    (including the Global stack, which has no workdir of its own) means
    no integration env vars, same as a plain, unmanaged directory."""
    stack = next((s for s in stacks_store.list_stacks() if s["workdir"] == workdir), None)
    if stack is None:
        return {}
    env = {}
    for integration_id in stack.get("integration_ids", []):
        integration = integrations_store.get(integration_id)
        if integration:
            env[integration["env_var"]] = integration["value"]
    return env


def _spawn(
    session_id: str, workdir: str, label: str, resume: bool, provider_id: str = "claude",
    cols: int | None = None, rows: int | None = None, unattended: bool = False,
) -> dict:
    with _lock:
        rt = _runtime.get(session_id)
        if rt is not None and rt["pty"].is_alive():
            return {"ok": True, "already_running": True, "pid": rt["pty"].pid}

        externals = pty_compat.find_pids_by_arg(session_id)
        if externals:
            return {"ok": True, "already_running": True, "pid": externals[0], "externally_managed": True}

        provider = providers.get(provider_id)
        args = (
            provider.resume_args(session_id, label, unattended) if resume
            else provider.new_session_args(session_id, label, unattended)
        )

        extra_env = {}
        if provider.api_key_env_var:
            key = settings.get(f"{provider_id}_api_key")
            if key:
                extra_env[provider.api_key_env_var] = key
        extra_env.update(_stack_integration_env(workdir))

        pty_session = pty_compat.PtySession(args, cwd=workdir, extra_env=extra_env or None, cols=cols, rows=rows)
        _runtime[session_id] = {
            "pty": pty_session,
            # Trimmed by total character count in _reader (see
            # MAX_BACKLOG_CHARS), not by item count -- deque() here is
            # unbounded on its own, popleft()'d manually instead.
            "output": deque(),
            "output_chars": 0,
            "provider": provider_id,
            "subscribers": [],
            "limit_hit": False,
            "limit_message": None,
            # Set True by _mark_ready once the trust prompt (if any) has
            # been handled and a short settle delay has passed -- see
            # _schedule_ready. A workflow run waits on this before writing
            # a prompt into a freshly spawned session.
            "ready": False,
        }
        t = threading.Thread(
            target=_reader, args=(session_id, pty_session, provider_id, unattended), daemon=True,
        )
        t.start()
        return {"ok": True, "already_running": False, "pid": pty_session.pid}


def start(
    session_id: str, cols: int | None = None, rows: int | None = None, unattended: bool = False,
) -> dict:
    entry = sessions_store.get(session_id)
    if entry is None:
        return {"ok": False, "error": "unknown session"}
    return _spawn(
        session_id, entry["workdir"], entry["label"], resume=True,
        provider_id=entry.get("provider", "claude"), cols=cols, rows=rows, unattended=unattended,
    )


def create(
    label: str, workdir: str, provider_id: str = "claude", unattended: bool = False, internal: bool = False,
    autostart: bool = True,
) -> dict:
    session_id = str(uuid_mod.uuid4())
    sessions_store.add(label, workdir, session_id=session_id, provider=provider_id, internal=internal)
    if autostart:
        result = _spawn(session_id, workdir, label, resume=False, provider_id=provider_id, unattended=unattended)
    else:
        # Caller (New Session's web form) will spawn this itself once its
        # own terminal view is open and has a real, correctly-fitted
        # cols/rows to hand to start() -- see terminal_hub.html's autostart
        # param. Spawning eagerly here would use _spawn()'s generic
        # wide-desktop guess (pty_compat.py's cols=None default), and a
        # freshly-spawned CLI whose live status/recap redraw assumed that
        # width can render corrupted once the browser's real (usually
        # narrower) size arrives moments later and forces a resize --
        # confirmed on a real Codex install 2026-08-12 ("wonky on startup,
        # fine after restart" -- restart already passes real cols/rows
        # since it's only ever triggered from an open terminal view).
        result = {"ok": True, "already_running": False, "pid": None}
    result["session_id"] = session_id
    return result


_WORKFLOW_READY_TIMEOUT = 30  # seconds -- see write()'s docstring for why a run waits on rt["ready"]


def _run_workflow(workflow_id: str) -> dict:
    """Runs a saved workflow once: resolves which session to use (a fresh
    one, or the workflow's own pinned one -- see workflows_store.py's
    session_mode), waits for it to actually be ready for input, then
    writes the workflow's prompt into it exactly the way a human typing
    it and hitting Enter would. Used by both the manual "Run Now" RPC and
    the (future) scheduler -- deliberately doesn't check workflow["enabled"]
    itself, since a manual run should still work on a disabled workflow;
    the scheduler is what's expected to filter on that before calling
    here."""
    workflow = workflows_store.get(workflow_id)
    if workflow is None:
        return {"ok": False, "error": "unknown workflow"}
    if workflow["stack_id"] == stacks_store.GLOBAL_STACK_ID:
        # The global team (~/.claude/agents) isn't tied to any one project
        # directory the way a real stack is -- it applies in any directory
        # with no project-level .claude/agents of its own, so the home
        # directory is a safe, neutral place to spawn its sessions.
        stack = {"workdir": str(Path.home())}
    else:
        stack = stacks_store.get(workflow["stack_id"])
    if stack is None:
        workflows_store.update(workflow_id, last_run_at=time.time(), last_run_status="error")
        return {"ok": False, "error": "workflow's stack no longer exists"}

    provider_id = workflow.get("provider") or "claude"
    unattended = bool(workflow.get("unattended"))

    if workflow.get("session_mode") == "reuse" and workflow.get("pinned_session_id"):
        session_id = workflow["pinned_session_id"]
        spawn_result = start(session_id, unattended=unattended)
    elif workflow.get("session_mode") == "reuse":
        label = f"Workflow: {workflow['name']}"
        spawn_result = create(label, stack["workdir"], provider_id, unattended=unattended)
        session_id = spawn_result.get("session_id")
        if session_id:
            workflows_store.update(workflow_id, pinned_session_id=session_id)
    else:  # "fresh" (default) -- a brand-new session every run
        label = f"Workflow: {workflow['name']}"
        spawn_result = create(label, stack["workdir"], provider_id, unattended=unattended)
        session_id = spawn_result.get("session_id")

    if not session_id or not spawn_result.get("ok"):
        workflows_store.update(workflow_id, last_run_at=time.time(), last_run_status="error")
        return {"ok": False, "error": "failed to start session for this workflow"}

    deadline = time.time() + _WORKFLOW_READY_TIMEOUT
    while time.time() < deadline:
        with _lock:
            rt = _runtime.get(session_id)
            if rt is not None and rt.get("ready"):
                break
        time.sleep(0.5)
    else:
        workflows_store.update(
            workflow_id, last_run_at=time.time(), last_run_status="error", last_run_session_id=session_id,
        )
        return {"ok": False, "error": "session never became ready for input", "session_id": session_id}

    write_result = write(session_id, workflow["prompt"])
    status_value = "ok" if write_result.get("ok") else "error"
    workflows_store.update(
        workflow_id, last_run_at=time.time(), last_run_status=status_value, last_run_session_id=session_id,
    )
    return {"ok": write_result.get("ok", False), "session_id": session_id}


def run_workflow_async(workflow_id: str) -> dict:
    """Fire-and-forget entry point for the run_workflow RPC -- _run_workflow
    itself can legitimately block for up to _WORKFLOW_READY_TIMEOUT (30s)
    waiting for a freshly spawned session to become ready, well past the
    TCP control channel's own 10s socket timeout (session_manager.py's
    _send). Runs it in a background thread instead and returns
    immediately; the caller (app.py's "Run Now" route) reads the actual
    outcome later from the workflow's own last_run_status/last_run_at,
    the same way session start/restart already work as a fire-and-see
    pattern backed by status polling."""
    threading.Thread(target=_run_workflow, args=(workflow_id,), daemon=True).start()
    return {"ok": True, "started": True}


def stop(session_id: str) -> dict:
    with _lock:
        rt = _runtime.pop(session_id, None)
        had_own = rt is not None and rt["pty"].is_alive()
        pid = rt["pty"].pid if rt else None
        if rt is not None and had_own:
            rt["pty"].terminate()

        externals = pty_compat.find_pids_by_arg(session_id)
        if externals:
            for p in externals:
                pty_compat.kill_pid(p)
            return {"ok": True, "was_running": True, "pid": externals[0]}
        return {"ok": True, "was_running": had_own, "pid": pid}


def restart(session_id: str, cols: int | None = None, rows: int | None = None) -> dict:
    stop_result = stop(session_id)
    start_result = start(session_id, cols=cols, rows=rows)
    return {"stopped": stop_result, "started": start_result}


def restart_all_running() -> list[str]:
    restarted = []
    for entry in sessions_store.list_sessions():
        if status(entry["id"])["running"]:
            restart(entry["id"])
            restarted.append(entry["id"])
    return restarted


def create_terminal_token(session_id: str) -> dict:
    """Short-lived, single-use token authorizing one websocket connection
    to one session's terminal. The websocket endpoint doesn't share
    app.py's Flask session cookie, so this is its own auth handoff:
    app.py only calls this for an already-authenticated dashboard user,
    then hands the token to the browser to open the websocket with."""
    token = secrets.token_urlsafe(32)
    _terminal_tokens[token] = (session_id, time.time() + _TOKEN_TTL_SECONDS)
    return {"ok": True, "token": token, "port": config.TERMINAL_PORT}


def _consume_terminal_token(token: str, session_id: str) -> bool:
    entry = _terminal_tokens.pop(token, None)
    if entry is None:
        return False
    expected_session_id, expires_at = entry
    if time.time() > expires_at:
        return False
    return secrets.compare_digest(expected_session_id, session_id)


async def _terminal_handler(websocket) -> None:
    try:
        path = websocket.request.path
    except AttributeError:
        path = websocket.path  # older websockets versions
    parts = path.strip("/").split("?", 1)
    if len(parts) != 2 or not parts[0].startswith("pty/"):
        await websocket.close(code=4000, reason="bad path")
        return
    session_id = parts[0][len("pty/"):]
    query = dict(p.split("=", 1) for p in parts[1].split("&") if "=" in p)
    token = query.get("token", "")

    if not _consume_terminal_token(token, session_id):
        await websocket.close(code=4001, reason="invalid or expired token")
        return

    with _lock:
        rt = _runtime.get(session_id)
        if rt is None or not rt["pty"].is_alive():
            await websocket.close(code=4004, reason="session not running")
            return
        pty_session = rt["pty"]
        backlog = "".join(rt["output"])
        queue: asyncio.Queue = asyncio.Queue()
        rt["subscribers"].append(queue)

    if backlog:
        await websocket.send(backlog)

    async def _pump_output():
        while True:
            text = await queue.get()
            await websocket.send(text)

    pump_task = asyncio.ensure_future(_pump_output())
    try:
        async for message in websocket:
            # Every client->server message is tagged with a 1-byte type
            # prefix so a resize control message can share this channel
            # with raw keystroke data without any ambiguity -- the tag is
            # always prepended by the client itself, never inferred from
            # the payload, so it's safe even though raw terminal input can
            # legitimately contain \x00/\x01 bytes (Ctrl+@, Ctrl+A).
            if message.startswith("\x01"):
                try:
                    size = json.loads(message[1:])
                    pty_session.resize(int(size["rows"]), int(size["cols"]))
                except (ValueError, KeyError, TypeError):
                    pass
            else:
                data = message[1:] if message.startswith("\x00") else message
                pty_session.write(data.encode("utf-8", errors="replace"))
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        pump_task.cancel()
        with _lock:
            rt = _runtime.get(session_id)
            if rt is not None and queue in rt["subscribers"]:
                rt["subscribers"].remove(queue)


def _run_terminal_server() -> None:
    global _ws_loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ws_loop = loop

    async def _serve():
        async with websockets.serve(_terminal_handler, config.HOST, config.TERMINAL_PORT):
            print(f"terminal websocket listening on {config.HOST}:{config.TERMINAL_PORT}")
            await asyncio.Future()  # run forever

    loop.run_until_complete(_serve())


_DISPATCH = {
    "status": lambda a: status(a["session_id"]),
    "get_output": lambda a: {"output": get_output(a["session_id"], a.get("max_chars", 8000))},
    "start": lambda a: start(a["session_id"], a.get("cols"), a.get("rows")),
    "stop": lambda a: stop(a["session_id"]),
    "restart": lambda a: restart(a["session_id"], a.get("cols"), a.get("rows")),
    "create": lambda a: create(a["label"], a["workdir"], a.get("provider", "claude"), internal=a.get("internal", False), autostart=a.get("autostart", True)),
    "restart_all_running": lambda a: {"restarted": restart_all_running()},
    "create_terminal_token": lambda a: create_terminal_token(a["session_id"]),
    "write": lambda a: write(a["session_id"], a["text"]),
    "run_workflow": lambda a: run_workflow_async(a["workflow_id"]),
    "start_mcp_connector_session": lambda a: start_mcp_connector_session_async(a["session_id"]),
    "get_mcp_connector_session_result": lambda a: get_mcp_connector_session_result(a["session_id"]),
    "ping": lambda a: {"ok": True},
}


# workflow_id -> epoch seconds of the last time the scheduler checked this
# workflow for a due fire. Deliberately in-memory/per-process, not persisted:
# on daemon startup every currently-enabled schedule workflow gets its
# baseline seeded on first sight rather than fired immediately, so a
# restart never floods-fires whatever schedules would otherwise look
# "overdue" from everything that happened while the daemon was down.
_scheduler_last_check: dict[str, float] = {}


def next_schedule_fire(cron_expr: str, base: float | None = None) -> float | None:
    """Used by both the scheduler loop below and app.py's "next run" display
    -- returns the next epoch-seconds fire time for a cron expression, or
    None if the expression doesn't parse."""
    try:
        it = croniter.croniter(cron_expr, datetime.fromtimestamp(base if base is not None else time.time()))
        return it.get_next(datetime).timestamp()
    except (ValueError, KeyError):
        return None


def _check_due_workflows() -> None:
    now = time.time()
    seen_ids = set()
    for wf in workflows_store.list_workflows():
        wid = wf["id"]
        seen_ids.add(wid)
        if not wf.get("enabled") or wf.get("trigger_type") != "schedule" or not wf.get("schedule"):
            continue

        last_check = _scheduler_last_check.get(wid)
        if last_check is None:
            _scheduler_last_check[wid] = now
            continue

        next_fire = next_schedule_fire(wf["schedule"], base=last_check)
        if next_fire is None:
            _scheduler_last_check[wid] = now
            continue
        if next_fire <= now:
            _scheduler_last_check[wid] = now
            run_workflow_async(wid)

    # Drop bookkeeping for workflows that no longer exist, so this dict
    # doesn't grow unbounded across a long-running daemon process.
    for wid in list(_scheduler_last_check):
        if wid not in seen_ids:
            del _scheduler_last_check[wid]


def _scheduler_loop() -> None:
    while True:
        time.sleep(30)
        try:
            _check_due_workflows()
        except Exception:
            # A scheduler bug should never be able to kill the whole
            # polling loop -- the next tick just tries again.
            pass


class Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        data = b""
        while not data.endswith(b"\n"):
            chunk = self.request.recv(65536)
            if not chunk:
                return
            data += chunk
        try:
            req = json.loads(data.decode("utf-8"))
            fn = _DISPATCH[req["cmd"]]
            resp = fn(req)
        except Exception as exc:  # noqa: BLE001 -- always report back over the socket
            resp = {"ok": False, "error": str(exc)}
        self.request.sendall((json.dumps(resp) + "\n").encode("utf-8"))


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    try:
        server = Server(("127.0.0.1", config.DAEMON_PORT), Handler)
    except OSError:
        print(
            f"Port {config.DAEMON_PORT} is already in use -- "
            "another daemon instance is probably already running.",
            file=sys.stderr,
        )
        sys.exit(1)

    ws_thread = threading.Thread(target=_run_terminal_server, daemon=True)
    ws_thread.start()

    scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    scheduler_thread.start()

    print(f"session_daemon listening on 127.0.0.1:{config.DAEMON_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
