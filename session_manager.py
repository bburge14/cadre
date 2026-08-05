"""Thin client for session_daemon.py -- see that file for why this is a
separate process rather than managing ptys/subprocesses in this one.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import config

SOCKET_PATH = config.INSTANCE_DIR / "daemon.sock"
_DAEMON_SCRIPT = config.BASE_DIR / "session_daemon.py"


def _send(payload: dict) -> dict:
    for attempt in range(2):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect(str(SOCKET_PATH))
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


def _ensure_daemon_running() -> None:
    if SOCKET_PATH.exists():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(str(SOCKET_PATH))
            return
        except OSError:
            pass
    subprocess.Popen(
        [sys.executable, str(_DAEMON_SCRIPT)],
        cwd=str(config.BASE_DIR),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    for _ in range(20):
        if SOCKET_PATH.exists():
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


def start(session_id: str) -> dict:
    return _send({"cmd": "start", "session_id": session_id})


def create(label: str, workdir: str) -> dict:
    return _send({"cmd": "create", "label": label, "workdir": workdir})


def stop(session_id: str) -> dict:
    return _send({"cmd": "stop", "session_id": session_id})


def restart(session_id: str) -> dict:
    return _send({"cmd": "restart", "session_id": session_id})


def restart_all_running() -> list[str]:
    resp = _send({"cmd": "restart_all_running", "session_id": None})
    return resp.get("restarted", [])
