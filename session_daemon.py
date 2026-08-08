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

import websockets
import websockets.exceptions

import config
import providers
import pty_compat
import sessions_store
import settings

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


def _reader(session_id: str, pty_session: pty_compat.PtySession, provider_id: str) -> None:
    trust_pattern = TRUST_PROMPT_PATTERNS.get(provider_id)
    trust_check_buffer = ""
    trust_handled = trust_pattern is None
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
            elif len(trust_check_buffer) > 20000:
                trust_check_buffer = trust_check_buffer[-5000:]

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


def _spawn(
    session_id: str, workdir: str, label: str, resume: bool, provider_id: str = "claude",
    cols: int | None = None, rows: int | None = None,
) -> dict:
    with _lock:
        rt = _runtime.get(session_id)
        if rt is not None and rt["pty"].is_alive():
            return {"ok": True, "already_running": True, "pid": rt["pty"].pid}

        externals = pty_compat.find_pids_by_arg(session_id)
        if externals:
            return {"ok": True, "already_running": True, "pid": externals[0], "externally_managed": True}

        provider = providers.get(provider_id)
        args = provider.resume_args(session_id, label) if resume else provider.new_session_args(session_id, label)

        extra_env = {}
        if provider.api_key_env_var:
            key = settings.get(f"{provider_id}_api_key")
            if key:
                extra_env[provider.api_key_env_var] = key

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
        }
        t = threading.Thread(target=_reader, args=(session_id, pty_session, provider_id), daemon=True)
        t.start()
        return {"ok": True, "already_running": False, "pid": pty_session.pid}


def start(session_id: str, cols: int | None = None, rows: int | None = None) -> dict:
    entry = sessions_store.get(session_id)
    if entry is None:
        return {"ok": False, "error": "unknown session"}
    return _spawn(
        session_id, entry["workdir"], entry["label"], resume=True,
        provider_id=entry.get("provider", "claude"), cols=cols, rows=rows,
    )


def create(label: str, workdir: str, provider_id: str = "claude") -> dict:
    session_id = str(uuid_mod.uuid4())
    sessions_store.add(label, workdir, session_id=session_id, provider=provider_id)
    result = _spawn(session_id, workdir, label, resume=False, provider_id=provider_id)
    result["session_id"] = session_id
    return result


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
    "get_output": lambda a: {"output": get_output(a["session_id"])},
    "start": lambda a: start(a["session_id"], a.get("cols"), a.get("rows")),
    "stop": lambda a: stop(a["session_id"]),
    "restart": lambda a: restart(a["session_id"], a.get("cols"), a.get("rows")),
    "create": lambda a: create(a["label"], a["workdir"], a.get("provider", "claude")),
    "restart_all_running": lambda a: {"restarted": restart_all_running()},
    "create_terminal_token": lambda a: create_terminal_token(a["session_id"]),
    "ping": lambda a: {"ok": True},
}


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

    print(f"session_daemon listening on 127.0.0.1:{config.DAEMON_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
