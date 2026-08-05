from __future__ import annotations

import hmac
import json
import secrets
import time
from functools import wraps

from flask import abort, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import config

_FAIL_TRACKER: dict[str, tuple[int, float]] = {}
_MAX_BACKOFF_SECONDS = 30


def admin_exists() -> bool:
    return config.ADMIN_FILE.exists()


def create_admin(username: str, password: str) -> None:
    data = {"username": username, "password_hash": generate_password_hash(password)}
    config.ADMIN_FILE.write_text(json.dumps(data))
    config.ADMIN_FILE.chmod(0o600)


def verify_login(username: str, password: str) -> bool:
    ip = request.remote_addr or "unknown"
    fail_count, last_fail = _FAIL_TRACKER.get(ip, (0, 0.0))
    backoff = min(2**fail_count, _MAX_BACKOFF_SECONDS) if fail_count else 0
    if time.time() - last_fail < backoff:
        return False

    if not admin_exists():
        return False
    data = json.loads(config.ADMIN_FILE.read_text())
    ok = secrets.compare_digest(username, data["username"]) and check_password_hash(
        data["password_hash"], password
    )
    if ok:
        _FAIL_TRACKER.pop(ip, None)
    else:
        _FAIL_TRACKER[ip] = (fail_count + 1, time.time())
    return ok


def log_in_session(username: str) -> None:
    session.clear()
    session["user"] = username
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


def log_out_session() -> None:
    session.clear()


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not admin_exists():
            return redirect(url_for("setup"))
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def check_csrf() -> None:
    """Call at the top of every state-changing POST route."""
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(submitted, expected):
        abort(400, description="Invalid or missing CSRF token.")
