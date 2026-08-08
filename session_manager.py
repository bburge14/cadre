"""Thin client for session_daemon.py -- see that file for why this is a
separate process rather than managing ptys/subprocesses in this one.
Talks to it over a TCP loopback socket (127.0.0.1 only), not a Unix
domain socket, so this same code works on Windows too.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import config

_DAEMON_ADDR = ("127.0.0.1", config.DAEMON_PORT)


def _daemon_launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        # Frozen build: the daemon is its own sibling executable (see
        # windows/*.spec + windows/installer.iss), not a .py script -- there
        # is no bundled Python interpreter to point at an arbitrary file.
        daemon_exe = Path(sys.executable).with_name("CadreDaemon.exe")
        return [str(daemon_exe)]
    return [sys.executable, str(config.BASE_DIR / "session_daemon.py")]


def _send(payload: dict) -> dict:
    for attempt in range(2):
        try:
            with socket.create_connection(_DAEMON_ADDR, timeout=10) as s:
                s.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                data = b""
                while not data.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                return json.loads(data.decode("utf-8"))
        except OSError:
            if attempt == 0:
                _ensure_daemon_running()
                time.sleep(0.5)
                continue
            return {"ok": False, "error": "could not reach session_daemon"}
    return {"ok": False, "error": "could not reach session_daemon"}


def _daemon_reachable() -> bool:
    try:
        with socket.create_connection(_DAEMON_ADDR, timeout=2):
            return True
    except OSError:
        return False


def _ensure_daemon_running() -> None:
    if _daemon_reachable():
        return

    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        import os

        kwargs["preexec_fn"] = os.setsid

    subprocess.Popen(
        _daemon_launch_command(),
        cwd=str(config.BASE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **kwargs,
    )
    for _ in range(20):
        if _daemon_reachable():
            return
        time.sleep(0.25)


def status(session_id: str) -> dict:
    resp = _send({"cmd": "status", "session_id": session_id})
    if not resp.get("ok", True) and "running" not in resp:
        return {"running": False, "pid": None, "externally_managed": False}
    return resp


def get_output(session_id: str, max_chars: int = 8000) -> str:
    resp = _send({"cmd": "get_output", "session_id": session_id})
    return resp.get("output", "")


def start(session_id: str, cols: int | None = None, rows: int | None = None) -> dict:
    return _send({"cmd": "start", "session_id": session_id, "cols": cols, "rows": rows})


def create(label: str, workdir: str, provider: str = "claude") -> dict:
    return _send({"cmd": "create", "label": label, "workdir": workdir, "provider": provider})


def stop(session_id: str) -> dict:
    return _send({"cmd": "stop", "session_id": session_id})


def restart(session_id: str, cols: int | None = None, rows: int | None = None) -> dict:
    return _send({"cmd": "restart", "session_id": session_id, "cols": cols, "rows": rows})


def restart_all_running() -> list[str]:
    resp = _send({"cmd": "restart_all_running", "session_id": None})
    return resp.get("restarted", [])


def create_terminal_token(session_id: str) -> dict:
    return _send({"cmd": "create_terminal_token", "session_id": session_id})


def send_input(session_id: str, text: str) -> dict:
    """Writes text into a running session's pty as if a human typed it and
    pressed Enter -- see session_daemon.py's write()."""
    return _send({"cmd": "write", "session_id": session_id, "text": text})


def run_workflow(workflow_id: str) -> dict:
    return _send({"cmd": "run_workflow", "workflow_id": workflow_id})
