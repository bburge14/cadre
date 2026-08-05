from __future__ import annotations

import os
import secrets
import subprocess
from datetime import timedelta
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for

import agents_store
import auth
import config
import git_hosts
import presets
import providers
import session_manager
import sessions_store
import settings
from auth import require_auth

app = Flask(
    __name__,
    template_folder=str(config.BUNDLE_DIR / "templates"),
    static_folder=str(config.BUNDLE_DIR / "static"),
)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COMMAND_CENTER_COOKIE_SECURE", "false").lower()
    in ("1", "true", "yes"),
)


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": auth.csrf_token}


@app.before_request
def enforce_csrf():
    if request.method == "POST" and request.endpoint not in ("setup", "login"):
        auth.check_csrf()


def _sessions_with_status() -> list[dict]:
    sessions = []
    for entry in sessions_store.list_sessions():
        sessions.append({**entry, "status": session_manager.status(entry["id"])})
    return sessions


# ---- Auth ----


@app.get("/setup")
def setup_form():
    if auth.admin_exists():
        return redirect(url_for("login"))
    return render_template("setup.html")


@app.post("/setup")
def setup():
    if auth.admin_exists():
        return redirect(url_for("login"))
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    if not username or not password:
        flash("Username and password are both required.", "error")
        return redirect(url_for("setup_form"))
    if password != confirm:
        flash("Passwords didn't match.", "error")
        return redirect(url_for("setup_form"))
    if len(password) < 8:
        flash("Password should be at least 8 characters.", "error")
        return redirect(url_for("setup_form"))
    auth.create_admin(username, password)
    auth.log_in_session(username)
    flash("Admin account created.", "success")
    return redirect(url_for("stacks_page"))


@app.get("/login")
def login_form():
    if not auth.admin_exists():
        return redirect(url_for("setup_form"))
    return render_template("login.html")


@app.post("/login")
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if auth.verify_login(username, password):
        auth.log_in_session(username)
        return redirect(url_for("index"))
    flash("Invalid username or password.", "error")
    return redirect(url_for("login_form"))


@app.get("/logout")
def logout():
    auth.log_out_session()
    return redirect(url_for("login_form"))


# ---- Dashboard ----


@app.get("/")
@require_auth
def index():
    return render_template(
        "index.html",
        agents=agents_store.list_agents(),
        sessions=_sessions_with_status(),
    )


# ---- Agents ----


def _other_active_agent_names(exclude: str | None) -> list[str]:
    return sorted(a.name for a in agents_store.list_agents() if a.name != exclude)


@app.get("/agents/new")
@require_auth
def new_agent_form():
    return render_template(
        "edit.html",
        agent=None,
        filename=None,
        base_tools_value="",
        spawnable=[],
        other_agents=_other_active_agent_names(exclude=None),
        cli_providers=[p for p in providers.list_providers() if p.id != "claude"],
    )


@app.get("/agents/<filename>/edit")
@require_auth
def edit_agent_form(filename):
    try:
        agent = agents_store.read_agent(filename)
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("index"))
    base_tools, spawnable = agents_store.parse_tools(agent.frontmatter.get("tools", ""))
    return render_template(
        "edit.html",
        agent=agent,
        filename=filename,
        base_tools_value=", ".join(base_tools),
        spawnable=spawnable,
        other_agents=_other_active_agent_names(exclude=agent.name),
        cli_providers=[p for p in providers.list_providers() if p.id != "claude"],
    )


@app.post("/agents/save")
@require_auth
def save_agent():
    filename = request.form.get("filename", "").strip()
    name = request.form.get("name", "").strip()
    if not filename:
        filename = f"{name}.md"

    frontmatter = {"name": name, "description": request.form.get("description", "").strip()}
    base_tools = [t.strip() for t in request.form.get("tools", "").split(",") if t.strip()]
    can_spawn = request.form.getlist("can_spawn")
    for key in ["model", "effort", "color"]:
        value = request.form.get(key, "").strip()
        if value:
            frontmatter[key] = value

    body = agents_store.strip_delegate_block(request.form.get("body", ""))

    primary_provider = request.form.get("primary_provider", "claude").strip() or "claude"
    if primary_provider != "claude":
        provider = providers.get(primary_provider)
        if "Bash" not in base_tools:
            base_tools.append("Bash")
        body = agents_store.build_delegate_block(provider) + body
        frontmatter["primary_provider"] = primary_provider

    tools_value = agents_store.serialize_tools(base_tools, can_spawn)
    if tools_value:
        frontmatter["tools"] = tools_value

    try:
        agents_store.write_agent(filename, frontmatter, body)
    except ValueError as exc:
        flash(f"Not saved: {exc}", "error")
        return redirect(url_for("index"))

    restarted = session_manager.restart_all_running()
    note = f" Restarted {len(restarted)} running session(s)." if restarted else ""
    flash(f"Saved {filename}.{note}", "success")
    return redirect(url_for("index"))


@app.post("/agents/<filename>/delete")
@require_auth
def delete_agent(filename):
    agents_store.delete_agent(filename)
    restarted = session_manager.restart_all_running()
    note = f" Restarted {len(restarted)} running session(s)." if restarted else ""
    flash(f"Deleted {filename}.{note}", "success")
    return redirect(url_for("index"))


# ---- Agent stack presets ----


def _resolve_target(target: str):
    """target is 'global', a session_id, or a raw absolute directory path
    (existing or brand new -- created here if it doesn't exist yet, so you
    can set up a stack for a project before ever creating a session there).
    Returns (agents_dir, session_id_or_None). agents_dir is None only for
    'global'. session_id is None for global OR a fresh custom directory
    with no session yet -- the caller distinguishes those by checking
    target == 'global' itself."""
    if target == "global" or not target:
        return None, None
    entry = sessions_store.get(target)
    if entry is not None:
        return agents_store.project_agents_dir(entry["workdir"]), entry["id"]

    path = Path(target).expanduser()
    if not path.is_absolute():
        raise ValueError(f"'{target}' isn't a known session or an absolute directory path.")
    path.mkdir(parents=True, exist_ok=True)
    return agents_store.project_agents_dir(str(path)), None


def _restart_for_target(target: str, session_id: str | None) -> None:
    if target == "global":
        session_manager.restart_all_running()
    elif session_id:
        session_manager.restart(session_id)
    # else: a brand-new custom directory with no session yet -- nothing running there to restart


@app.get("/stacks")
@require_auth
def stacks_page():
    target = request.args.get("target", "global")
    session_ids = {s["id"] for s in sessions_store.list_sessions()}
    is_custom_path = target not in ("global",) and target not in session_ids
    try:
        agents_dir, _session_id = _resolve_target(target)
    except ValueError:
        target = "global"
        agents_dir = None
        is_custom_path = False
    active_names = {a.name for a in agents_store.list_agents(agents_dir=agents_dir)}
    return render_template(
        "stacks.html",
        stack_presets=presets.list_presets(),
        library=presets.list_library_agents(),
        active_names=active_names,
        sessions=sessions_store.list_sessions(),
        target=target,
        is_custom_path=is_custom_path,
    )


@app.post("/stacks/activate-preset")
@require_auth
def activate_preset():
    preset_id = request.form.get("preset_id", "")
    target = request.form.get("custom_target", "").strip() or request.form.get("target", "global")
    try:
        agents_dir, session_id = _resolve_target(target)
        written = presets.activate_preset(preset_id, agents_dir=agents_dir)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("stacks_page"))
    _restart_for_target(target, session_id)
    flash(f"Activated {len(written)} agent(s) for {'global' if target == 'global' else target}.", "success")
    return redirect(url_for("stacks_page", target=target))


@app.post("/stacks/activate-custom")
@require_auth
def activate_custom():
    agent_ids = request.form.getlist("agent_ids")
    target = request.form.get("custom_target", "").strip() or request.form.get("target", "global")
    try:
        agents_dir, session_id = _resolve_target(target)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("stacks_page"))
    written = presets.activate(agent_ids, agents_dir=agents_dir)
    _restart_for_target(target, session_id)
    flash(f"Activated {len(written)} agent(s) for {'global' if target == 'global' else target}.", "success")
    return redirect(url_for("stacks_page", target=target))


@app.get("/stacks/diagram")
@require_auth
def stacks_diagram():
    active = agents_store.list_agents()
    nodes = []
    for a in active:
        base_tools, spawnable = agents_store.parse_tools(a.frontmatter.get("tools", ""))
        nodes.append(
            {
                "filename": a.filename,
                "name": a.name,
                "spawnable": spawnable,
                "others": [o.name for o in active if o.name != a.name],
            }
        )
    return render_template("stacks_diagram.html", nodes=nodes)


@app.post("/stacks/diagram/set-spawnable")
@require_auth
def set_spawnable():
    filename = request.form.get("agent_filename", "")
    can_spawn = request.form.getlist("can_spawn")
    try:
        agent = agents_store.read_agent(filename)
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("stacks_diagram"))
    base_tools, _old_spawnable = agents_store.parse_tools(agent.frontmatter.get("tools", ""))
    frontmatter = dict(agent.frontmatter)
    tools_value = agents_store.serialize_tools(base_tools, can_spawn)
    if tools_value:
        frontmatter["tools"] = tools_value
    else:
        frontmatter.pop("tools", None)
    agents_store.write_agent(filename, frontmatter, agent.body)
    session_manager.restart_all_running()
    return redirect(url_for("stacks_diagram"))


# ---- Sessions ----


@app.get("/sessions/new")
@require_auth
def new_session_form():
    return render_template(
        "session_form.html",
        session=None,
        github_connected=bool(git_hosts.get_token("github")),
        github_configured=bool(settings.get("github_client_id")),
        gitlab_connected=bool(git_hosts.get_token("gitlab")),
        gitlab_configured=bool(settings.get("gitlab_client_id")),
        cli_providers=providers.list_providers(),
    )


@app.post("/sessions/new")
@require_auth
def create_session():
    label = request.form.get("label", "").strip()
    source = request.form.get("source", "local")

    if source in ("github", "gitlab"):
        repo_full_name = request.form.get("repo_full_name", "").strip()
        token = git_hosts.get_token(source)
        if not repo_full_name or not token:
            flash(f"Pick a repo to clone from {source.title()}.", "error")
            return redirect(url_for("new_session_form"))
        try:
            list_repos = git_hosts.github_list_repos if source == "github" else git_hosts.gitlab_list_repos
            clone_url_for = git_hosts.github_clone_url_for if source == "github" else git_hosts.gitlab_clone_url_for
            repos = list_repos(token)
            clone_url = clone_url_for(repo_full_name, repos)
        except Exception as exc:
            flash(f"Couldn't look up that repo: {exc}", "error")
            return redirect(url_for("new_session_form"))

        projects_root = settings.projects_root()
        target_dir = projects_root / git_hosts.slugify_repo_name(repo_full_name)
        suffix = 2
        while target_dir.exists():
            target_dir = projects_root / f"{git_hosts.slugify_repo_name(repo_full_name)}-{suffix}"
            suffix += 1

        clone_cmd = [
            "git", "clone",
            "--config", f"http.extraheader=Authorization: Bearer {token}",
            clone_url, str(target_dir),
        ]
        result = subprocess.run(clone_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            flash(f"Clone failed: {result.stderr.strip()[-300:]}", "error")
            return redirect(url_for("new_session_form"))
        workdir = str(target_dir)
        if not label:
            label = repo_full_name
    else:
        workdir = request.form.get("workdir", "").strip()
        if not label or not workdir:
            flash("Label and working directory are both required.", "error")
            return redirect(url_for("new_session_form"))
        if not Path(workdir).is_dir():
            flash(f"'{workdir}' is not a directory that exists on this machine.", "error")
            return redirect(url_for("new_session_form"))

    provider_id = request.form.get("provider", "claude") if source == "local" else "claude"
    result = session_manager.create(label, workdir, provider=provider_id)
    flash(f"Created session '{label}' (pid {result.get('pid')}).", "success")
    return redirect(url_for("index"))


# ---- Settings ----


SECRET_SETTINGS = {
    "github_client_secret", "gitlab_client_secret",
    "gemini_api_key", "codex_api_key", "kimi_api_key",
}


@app.get("/settings")
@require_auth
def settings_form():
    raw = settings.get_all()
    # Secrets never round-trip into the page -- not even masked in a value
    # attribute, since that's still plaintext in the HTML source. Only a
    # boolean "is one set" flag reaches the template.
    values = {k: ("" if k in SECRET_SETTINGS else v) for k, v in raw.items()}
    secrets_set = {k: bool(raw[k]) for k in SECRET_SETTINGS}
    return render_template(
        "settings.html",
        values=values,
        secrets_set=secrets_set,
        github_callback_url=url_for("github_oauth_callback", _external=True),
        github_connected=bool(git_hosts.get_token("github")),
        gitlab_callback_url=url_for("gitlab_oauth_callback", _external=True),
        gitlab_connected=bool(git_hosts.get_token("gitlab")),
    )


@app.post("/settings")
@require_auth
def save_settings():
    fields = {
        "github_client_id": request.form.get("github_client_id", ""),
        "gitlab_base_url": request.form.get("gitlab_base_url", "").rstrip("/") or "https://gitlab.com",
        "gitlab_client_id": request.form.get("gitlab_client_id", ""),
        "projects_root": request.form.get("projects_root", ""),
    }
    # Secret fields: the form never shows the existing value, so a blank
    # submission means "leave it as-is," not "clear it" -- only overwrite
    # when the user actually typed something.
    for key in SECRET_SETTINGS:
        value = request.form.get(key, "").strip()
        if value:
            fields[key] = value
    settings.update(**fields)
    flash("Settings saved.", "success")
    return redirect(url_for("settings_form"))


# ---- Git host OAuth ----


@app.get("/oauth/github/start")
@require_auth
def github_oauth_start():
    if not settings.get("github_client_id"):
        flash("Add a GitHub Client ID/Secret in Settings first.", "error")
        return redirect(url_for("settings_form"))
    state = secrets.token_urlsafe(32)
    session["github_oauth_state"] = state
    redirect_uri = url_for("github_oauth_callback", _external=True)
    return redirect(git_hosts.github_authorize_url(redirect_uri, state))


@app.get("/oauth/github/callback")
@require_auth
def github_oauth_callback():
    expected_state = session.pop("github_oauth_state", None)
    got_state = request.args.get("state")
    if not expected_state or not secrets.compare_digest(expected_state, got_state or ""):
        flash("GitHub OAuth state mismatch -- please try connecting again.", "error")
        return redirect(url_for("new_session_form"))

    code = request.args.get("code")
    if not code:
        flash("GitHub didn't return an authorization code.", "error")
        return redirect(url_for("new_session_form"))

    redirect_uri = url_for("github_oauth_callback", _external=True)
    try:
        token = git_hosts.github_exchange_code(code, redirect_uri)
    except Exception as exc:
        flash(f"GitHub token exchange failed: {exc}", "error")
        return redirect(url_for("new_session_form"))

    git_hosts.set_token("github", token)
    flash("GitHub connected.", "success")
    return redirect(url_for("new_session_form"))


@app.get("/oauth/github/repos.json")
@require_auth
def github_repos_json():
    token = git_hosts.get_token("github")
    if not token:
        return {"repos": [], "connected": False}
    try:
        repos = git_hosts.github_list_repos(token)
    except Exception as exc:
        return {"repos": [], "connected": True, "error": str(exc)}
    return {"repos": repos, "connected": True}


@app.get("/oauth/gitlab/start")
@require_auth
def gitlab_oauth_start():
    if not settings.get("gitlab_client_id"):
        flash("Add a GitLab Application ID/Secret in Settings first.", "error")
        return redirect(url_for("settings_form"))
    state = secrets.token_urlsafe(32)
    session["gitlab_oauth_state"] = state
    redirect_uri = url_for("gitlab_oauth_callback", _external=True)
    return redirect(git_hosts.gitlab_authorize_url(redirect_uri, state))


@app.get("/oauth/gitlab/callback")
@require_auth
def gitlab_oauth_callback():
    expected_state = session.pop("gitlab_oauth_state", None)
    got_state = request.args.get("state")
    if not expected_state or not secrets.compare_digest(expected_state, got_state or ""):
        flash("GitLab OAuth state mismatch -- please try connecting again.", "error")
        return redirect(url_for("new_session_form"))

    code = request.args.get("code")
    if not code:
        flash("GitLab didn't return an authorization code.", "error")
        return redirect(url_for("new_session_form"))

    redirect_uri = url_for("gitlab_oauth_callback", _external=True)
    try:
        token = git_hosts.gitlab_exchange_code(code, redirect_uri)
    except Exception as exc:
        flash(f"GitLab token exchange failed: {exc}", "error")
        return redirect(url_for("new_session_form"))

    git_hosts.set_token("gitlab", token)
    flash("GitLab connected.", "success")
    return redirect(url_for("new_session_form"))


@app.get("/oauth/gitlab/repos.json")
@require_auth
def gitlab_repos_json():
    token = git_hosts.get_token("gitlab")
    if not token:
        return {"repos": [], "connected": False}
    try:
        repos = git_hosts.gitlab_list_repos(token)
    except Exception as exc:
        return {"repos": [], "connected": True, "error": str(exc)}
    return {"repos": repos, "connected": True}


@app.get("/sessions/<session_id>")
@require_auth
def session_detail(session_id):
    entry = sessions_store.get(session_id)
    if entry is None:
        flash("Unknown session.", "error")
        return redirect(url_for("index"))
    return render_template(
        "session_detail.html", session=entry, status=session_manager.status(session_id)
    )


@app.get("/sessions/<session_id>/edit")
@require_auth
def edit_session_form(session_id):
    entry = sessions_store.get(session_id)
    if entry is None:
        flash("Unknown session.", "error")
        return redirect(url_for("index"))
    return render_template("session_form.html", session=entry)


@app.post("/sessions/<session_id>/edit")
@require_auth
def edit_session(session_id):
    label = request.form.get("label", "").strip()
    workdir = request.form.get("workdir", "").strip()
    if not label or not workdir:
        flash("Label and working directory are both required.", "error")
        return redirect(url_for("edit_session_form", session_id=session_id))
    sessions_store.update(session_id, label=label, workdir=workdir)
    flash("Session updated. Restart it to apply a changed working directory.", "success")
    return redirect(url_for("index"))


@app.post("/sessions/<session_id>/<action>")
@require_auth
def session_action(session_id, action):
    if action == "start":
        session_manager.start(session_id)
    elif action == "stop":
        session_manager.stop(session_id)
    elif action == "restart":
        session_manager.restart(session_id)
    elif action == "delete":
        session_manager.stop(session_id)
        wipe_history = request.form.get("wipe_history") == "on"
        if wipe_history:
            for path in Path.home().glob(f".claude/projects/*/{session_id}.jsonl"):
                path.unlink(missing_ok=True)
        sessions_store.remove(session_id)
        flash("Session deleted.", "success")
        return redirect(url_for("index"))
    else:
        flash("Unknown action", "error")
    return redirect(url_for("index"))


@app.get("/sessions/<session_id>/status.json")
@require_auth
def session_status_json(session_id):
    return {
        **session_manager.status(session_id),
        "output": session_manager.get_output(session_id),
    }


@app.post("/sessions/<session_id>/terminal-token")
@require_auth
def session_terminal_token(session_id):
    if sessions_store.get(session_id) is None:
        return {"ok": False, "error": "unknown session"}, 404
    return session_manager.create_terminal_token(session_id)


if __name__ == "__main__":
    app.run(host=config.HOST, port=config.PORT, threaded=True)
