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
_RECOVERY_FAIL_TRACKER: dict[str, tuple[int, float]] = {}
_MAX_BACKOFF_SECONDS = 30


def _backoff_ok(tracker: dict, key: str) -> bool:
    fail_count, last_fail = tracker.get(key, (0, 0.0))
    backoff = min(2**fail_count, _MAX_BACKOFF_SECONDS) if fail_count else 0
    return time.time() - last_fail >= backoff


def _record_backoff_result(tracker: dict, key: str, ok: bool) -> None:
    if ok:
        tracker.pop(key, None)
    else:
        fail_count, _ = tracker.get(key, (0, 0.0))
        tracker[key] = (fail_count + 1, time.time())


def admin_exists() -> bool:
    return config.ADMIN_FILE.exists()


def _normalize_answer(answer: str) -> str:
    return answer.strip().lower()


def create_admin(username: str, password: str, security_question: str, security_answer: str) -> None:
    data = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "security_question": security_question,
        "security_answer_hash": generate_password_hash(_normalize_answer(security_answer)),
    }
    config.ADMIN_FILE.write_text(json.dumps(data))
    config.ADMIN_FILE.chmod(0o600)


def get_username() -> str | None:
    if not admin_exists():
        return None
    return json.loads(config.ADMIN_FILE.read_text()).get("username")


def has_security_question() -> bool:
    if not admin_exists():
        return False
    return bool(json.loads(config.ADMIN_FILE.read_text()).get("security_question"))


def get_security_question(username: str) -> str | None:
    """Only returns the question if `username` actually matches the
    stored account -- an arbitrary typed-in username shouldn't be able
    to fish for whether/what question exists."""
    if not admin_exists():
        return None
    data = json.loads(config.ADMIN_FILE.read_text())
    if not secrets.compare_digest(username, data.get("username", "")):
        return None
    return data.get("security_question")


def verify_login(username: str, password: str) -> bool:
    ip = request.remote_addr or "unknown"
    if not _backoff_ok(_FAIL_TRACKER, ip):
        return False
    if not admin_exists():
        return False
    data = json.loads(config.ADMIN_FILE.read_text())
    ok = secrets.compare_digest(username, data["username"]) and check_password_hash(
        data["password_hash"], password
    )
    _record_backoff_result(_FAIL_TRACKER, ip, ok)
    return ok


def reset_password_via_security(username: str, answer: str, new_password: str) -> tuple[bool, str]:
    """The recovery path for someone locked out with no terminal access
    to the machine -- verifies the security answer (rate-limited same as
    login) and sets a new password if it matches. Generic error message
    on failure either way (unknown username vs. wrong answer) to avoid
    leaking which one was wrong."""
    ip = request.remote_addr or "unknown"
    if not _backoff_ok(_RECOVERY_FAIL_TRACKER, ip):
        return False, "Too many attempts -- wait a moment and try again."
    if not admin_exists():
        return False, "No admin account exists."

    data = json.loads(config.ADMIN_FILE.read_text())
    username_ok = secrets.compare_digest(username, data.get("username", ""))
    answer_hash = data.get("security_answer_hash", "")
    answer_ok = bool(answer_hash) and check_password_hash(answer_hash, _normalize_answer(answer))
    ok = username_ok and answer_ok
    _record_backoff_result(_RECOVERY_FAIL_TRACKER, ip, ok)
    if not ok:
        return False, "Username or answer is incorrect."

    data["password_hash"] = generate_password_hash(new_password)
    config.ADMIN_FILE.write_text(json.dumps(data))
    config.ADMIN_FILE.chmod(0o600)
    return True, ""


def change_credentials(
    current_password: str,
    new_username: str | None = None,
    new_password: str | None = None,
    new_security_question: str | None = None,
    new_security_answer: str | None = None,
) -> tuple[bool, str]:
    """Self-service credential changes from Settings while logged in --
    always requires the current password, same as any real account
    settings page. Each new_* is optional/independent: pass only what
    you're actually changing."""
    if not admin_exists():
        return False, "No admin account exists."
    data = json.loads(config.ADMIN_FILE.read_text())
    if not check_password_hash(data["password_hash"], current_password):
        return False, "Current password is incorrect."

    if new_username:
        data["username"] = new_username
    if new_password:
        data["password_hash"] = generate_password_hash(new_password)
    if new_security_question:
        data["security_question"] = new_security_question
    if new_security_answer:
        data["security_answer_hash"] = generate_password_hash(_normalize_answer(new_security_answer))

    config.ADMIN_FILE.write_text(json.dumps(data))
    config.ADMIN_FILE.chmod(0o600)
    return True, ""


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
