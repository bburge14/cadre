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

import json
import re
import socketserver
import sys
import threading
import uuid as uuid_mod
from collections import deque

import config
import providers
import pty_compat
import sessions_store
import settings

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

_lock = threading.Lock()
_runtime: dict[str, dict] = {}


def _reader(session_id: str, pty_session: pty_compat.PtySession, provider_id: str) -> None:
    trust_pattern = TRUST_PROMPT_PATTERNS.get(provider_id)
    trust_check_buffer = ""
    trust_handled = trust_pattern is None
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


def status(session_id: str) -> dict:
    with _lock:
        rt = _runtime.get(session_id)
        own_running = rt is not None and rt["pty"].is_alive()
        own_pid = rt["pty"].pid if rt else None
        pid = own_pid if own_running else None
    externally_managed = False
    if not own_running:
        externals = pty_compat.find_pids_by_arg(session_id, own_pid)
        if externals:
            own_running = True
            pid = externals[0]
            externally_managed = True
    return {"running": own_running, "pid": pid, "externally_managed": externally_managed}


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


def _spawn(session_id: str, workdir: str, label: str, resume: bool, provider_id: str = "claude") -> dict:
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

        pty_session = pty_compat.PtySession(args, cwd=workdir, extra_env=extra_env or None)
        _runtime[session_id] = {"pty": pty_session, "output": deque(maxlen=2000), "provider": provider_id}
        t = threading.Thread(target=_reader, args=(session_id, pty_session, provider_id), daemon=True)
        t.start()
        return {"ok": True, "already_running": False, "pid": pty_session.pid}


def start(session_id: str) -> dict:
    entry = sessions_store.get(session_id)
    if entry is None:
        return {"ok": False, "error": "unknown session"}
    return _spawn(session_id, entry["workdir"], entry["label"], resume=True, provider_id=entry.get("provider", "claude"))


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


def restart(session_id: str) -> dict:
    stop_result = stop(session_id)
    start_result = start(session_id)
    return {"stopped": stop_result, "started": start_result}


def restart_all_running() -> list[str]:
    restarted = []
    for entry in sessions_store.list_sessions():
        if status(entry["id"])["running"]:
            restart(entry["id"])
            restarted.append(entry["id"])
    return restarted


_DISPATCH = {
    "status": lambda a: status(a["session_id"]),
    "get_output": lambda a: {"output": get_output(a["session_id"])},
    "start": lambda a: start(a["session_id"]),
    "stop": lambda a: stop(a["session_id"]),
    "restart": lambda a: restart(a["session_id"]),
    "create": lambda a: create(a["label"], a["workdir"], a.get("provider", "claude")),
    "restart_all_running": lambda a: {"restarted": restart_all_running()},
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
    print(f"session_daemon listening on 127.0.0.1:{config.DAEMON_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
