"""Long-running process that owns every session's pty and subprocess.

Deliberately kept separate from app.py: the whole point is that a session's
aliveness depends on this process staying up (its pty master fd must stay
open and read from), so restarting/redeploying the *web app* must never be
what kills a live session. This process should only need restarting for
its own bug fixes, which are rare -- routine app.py/template/auth changes
never touch it.
"""
from __future__ import annotations

import json
import os
import pty
import re
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid as uuid_mod
from collections import deque

import config
import sessions_store

CLAUDE_BIN = config.CLAUDE_BIN
SOCKET_PATH = config.INSTANCE_DIR / "daemon.sock"

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ANSI_OTHER_RE = re.compile(r"\x1b[^\[]")

_lock = threading.Lock()
_runtime: dict[str, dict] = {}


def _external_pids(session_id: str, own_pid: int | None) -> list[int]:
    try:
        result = subprocess.run(["pgrep", "-f", session_id], capture_output=True, text=True)
    except FileNotFoundError:
        return []
    pids = [int(p) for p in result.stdout.split() if p.strip()]
    if own_pid is not None:
        pids = [p for p in pids if p != own_pid]
    return pids


def _kill_pids(pids: list[int]) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    if pids:
        time.sleep(1)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _reader(session_id: str, master_fd: int) -> None:
    trust_check_buffer = ""
    trust_handled = False
    while True:
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
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
            if "trustthisfolder" in plain_nospace:
                try:
                    os.write(master_fd, b"1\r")
                except OSError:
                    pass
                trust_handled = True
            elif len(trust_check_buffer) > 20000:
                trust_check_buffer = trust_check_buffer[-5000:]


def status(session_id: str) -> dict:
    with _lock:
        rt = _runtime.get(session_id)
        own_running = rt is not None and rt["proc"].poll() is None
        own_pid = rt["proc"].pid if rt else None
        pid = own_pid if own_running else None
    externally_managed = False
    if not own_running:
        externals = _external_pids(session_id, own_pid)
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


def _spawn(session_id: str, workdir: str, label: str, resume: bool) -> dict:
    with _lock:
        rt = _runtime.get(session_id)
        if rt is not None and rt["proc"].poll() is None:
            return {"ok": True, "already_running": True, "pid": rt["proc"].pid}

        externals = _external_pids(session_id, None)
        if externals:
            return {"ok": True, "already_running": True, "pid": externals[0], "externally_managed": True}

        args = [CLAUDE_BIN]
        args += ["--resume", session_id] if resume else ["--session-id", session_id]
        args += ["--remote-control", label]

        master_fd, slave_fd = pty.openpty()
        proc = subprocess.Popen(
            args, cwd=workdir, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            preexec_fn=os.setsid, close_fds=True,
        )
        os.close(slave_fd)
        _runtime[session_id] = {"proc": proc, "master_fd": master_fd, "output": deque(maxlen=2000)}
        t = threading.Thread(target=_reader, args=(session_id, master_fd), daemon=True)
        t.start()
        return {"ok": True, "already_running": False, "pid": proc.pid}


def start(session_id: str) -> dict:
    entry = sessions_store.get(session_id)
    if entry is None:
        return {"ok": False, "error": "unknown session"}
    return _spawn(session_id, entry["workdir"], entry["label"], resume=True)


def create(label: str, workdir: str) -> dict:
    session_id = str(uuid_mod.uuid4())
    sessions_store.add(label, workdir, session_id=session_id)
    result = _spawn(session_id, workdir, label, resume=False)
    result["session_id"] = session_id
    return result


def stop(session_id: str) -> dict:
    with _lock:
        rt = _runtime.pop(session_id, None)
        had_own = rt is not None and rt["proc"].poll() is None
        pid = rt["proc"].pid if rt else None
        if rt is not None:
            if had_own:
                try:
                    os.killpg(os.getpgid(rt["proc"].pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    rt["proc"].wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(rt["proc"].pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            try:
                os.close(rt["master_fd"])
            except OSError:
                pass

        externals = _external_pids(session_id, None)
        if externals:
            _kill_pids(externals)
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
    "create": lambda a: create(a["label"], a["workdir"]),
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


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    if SOCKET_PATH.exists():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(str(SOCKET_PATH))
            print("Another daemon instance is already listening; exiting.", file=sys.stderr)
            sys.exit(1)
        except OSError:
            SOCKET_PATH.unlink()

    server = Server(str(SOCKET_PATH), Handler)
    os.chmod(SOCKET_PATH, 0o600)
    print(f"session_daemon listening on {SOCKET_PATH}")
    try:
        server.serve_forever()
    finally:
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
