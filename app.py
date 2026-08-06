from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import timedelta
from pathlib import Path

import requests
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
import skills_store
import stacks_store
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
    SESSION_COOKIE_SECURE=config.COOKIE_SECURE,
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
    return redirect(url_for("wizard_form"))


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


# ---- Setup wizard: pick an AI, connect it, set it as the default/orchestrator ----


@app.get("/wizard")
@require_auth
def wizard_form():
    return render_template(
        "wizard.html",
        providers=providers.list_providers(),
        provider_binaries={p.id: providers.binary_found(p.id) for p in providers.list_providers()},
        usable={p.id: providers.usable(p.id) for p in providers.list_providers()},
        claude_installed=providers.binary_found("claude"),
        claude_logged_in=providers.claude_logged_in(),
        secrets_set={f"{p.id}_api_key": bool(settings.get(f"{p.id}_api_key")) for p in providers.list_providers() if p.api_key_env_var},
        default_provider=settings.get("default_provider"),
    )


@app.post("/wizard/connect")
@require_auth
def wizard_connect():
    provider_id = request.form.get("provider", "")
    try:
        provider = providers.get(provider_id)
    except ValueError:
        flash("Unknown provider.", "error")
        return redirect(url_for("wizard_form"))
    if provider.api_key_env_var:
        api_key = request.form.get("api_key", "").strip()
        if api_key:
            settings.update(**{f"{provider_id}_api_key": api_key})
            flash(f"{provider.label} API key saved.", "success")
    return redirect(url_for("wizard_form"))


@app.post("/wizard/set-default")
@require_auth
def wizard_set_default():
    provider_id = request.form.get("provider", "")
    try:
        provider = providers.get(provider_id)
    except ValueError:
        flash("Unknown provider.", "error")
        return redirect(url_for("wizard_form"))
    if provider_id not in {p.id for p in providers.orchestration_candidates()}:
        flash(f"{provider.label} can't be set as the default yet -- it isn't connected, or can't run Agent Stacks.", "error")
        return redirect(url_for("wizard_form"))
    settings.update(default_provider=provider_id)
    flash(f"{provider.label} is now your default AI.", "success")
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    auth.log_out_session()
    return redirect(url_for("login_form"))


# ---- Dashboard ----


def _stacks_with_agent_counts() -> list[dict]:
    global_stack = _resolve_stack(_GLOBAL_STACK_ID)
    stacks = [{**global_stack, "agent_count": len(agents_store.list_agents())}]
    for s in stacks_store.list_stacks():
        agents_dir = agents_store.project_agents_dir(s["workdir"])
        stacks.append({**s, "agent_count": len(agents_store.list_agents(agents_dir=agents_dir))})
    return stacks


@app.get("/")
@require_auth
def index():
    return render_template(
        "index.html",
        stacks=_stacks_with_agent_counts(),
        sessions=_sessions_with_status(),
    )


@app.get("/docs")
@require_auth
def docs_page():
    return render_template("docs.html")


# ---- Stacks (including the synthetic "global" default stack) ----

# "global" isn't a real stacks_store record -- it's the one team Claude Code
# itself always falls back to (~/.claude/agents/, ~/.claude/skills/) when a
# session isn't rooted in a directory any real stack covers. Representing
# it as a synthetic entry with this reserved id means every agent/skill/
# diagram route below can treat it identically to a real stack (same CRUD,
# same templates) instead of needing a second, parallel set of pages --
# it just can't be renamed, moved, or deleted, since there's no directory
# to point elsewhere and no meaningful "delete" for the one true fallback.
_GLOBAL_STACK_ID = "global"
_GLOBAL_SEEDED_MARKER = config.INSTANCE_DIR / "global_seeded"
_GLOBAL_SKILLS_SEEDED_MARKER = config.INSTANCE_DIR / "global_skills_seeded"

# Three example skills, one per major flavor the Generalist preset spans
# (coding / writing / research), seeded into the default stack so there's
# a concrete answer to "what's a skill actually for" instead of an empty
# list and an abstract explanation. Each is a genuinely usable starting
# point, not just filler -- edit or delete freely.
_DEFAULT_SKILLS = [
    (
        "commit-message-style",
        "Reference for how commit messages should be written for this "
        "project -- tone, structure, what to include. Use when writing a "
        "git commit message.",
        "Keep the summary line under ~70 characters, imperative mood "
        '("add", "fix", "remove" -- not "added"/"adding"). Explain *why* '
        "the change was made in the body if it isn't obvious from the "
        'summary alone -- not a restatement of the diff ("various '
        'changes", "update files") but the actual reason: a bug being '
        "fixed, a decision being made, a constraint being worked around. "
        "Skip a body entirely for genuinely self-explanatory changes "
        "rather than padding one out. Never mention this skill, an AI, or "
        "a tool in the message itself.",
    ),
    (
        "writing-tone-guide",
        "Reference for tone and style when drafting anything meant for "
        "someone else to read -- docs, emails, reports, UI copy. Use "
        "before finishing a piece of writing, not just at the very start.",
        "Plain language over jargon; if a technical term is necessary, "
        "the first use should make its meaning clear from context. Active "
        "voice, concrete nouns, short sentences -- cut a sentence in half "
        "before reaching for a semicolon. Say the specific thing, not the "
        'vague-but-safe thing ("saves about 40% on average" beats '
        '"significantly improves efficiency"). Cut filler and hedging '
        '("essentially", "in order to", "it should be noted that") on a '
        "final pass. Match formality to the actual audience and channel "
        "-- an internal Slack update and a customer-facing doc shouldn't "
        "read the same.",
    ),
    (
        "research-source-checklist",
        "Checklist for evaluating how trustworthy and current a source "
        "is before relying on it. Use when researching something where "
        "accuracy actually matters, not casual browsing.",
        "Prefer primary/authoritative sources (official docs, the "
        "source's own changelog or issue tracker, a spec or standard) "
        "over blog posts, forum answers, or aggregator sites that "
        "summarize them secondhand. For anything version- or "
        "date-sensitive, find and state the actual version/date rather "
        "than assuming the newest applies. When sources disagree, say so "
        "explicitly instead of silently picking one and presenting it as "
        "settled. Note how current a source is, especially for anything "
        "in a fast-moving space -- a two-year-old answer about a library's "
        "API surface is a real risk, not just a formality to skip.",
    ),
]


def _ensure_global_seeded() -> None:
    """The default stack shouldn't just be empty scaffolding -- seed it
    with the Generalist preset the first time it's ever found empty, so a
    fresh install (or one that's simply never had anything activated into
    ~/.claude/agents/ yet) has something in it out of the box. Runs once
    -- marked via a sentinel file so deliberately clearing it out later
    doesn't cause it to keep coming back. Skills get their own independent
    marker/check (not gated behind the same one as agents) since they're
    an unrelated concern that can legitimately still be empty even after
    agents have already been seeded or hand-populated."""
    if not _GLOBAL_SEEDED_MARKER.exists():
        if not agents_store.list_agents():
            presets.activate_preset("generalist", agents_dir=agents_store.AGENTS_DIR)
        _GLOBAL_SEEDED_MARKER.write_text("seeded\n")

    if not _GLOBAL_SKILLS_SEEDED_MARKER.exists():
        if not skills_store.list_skills():
            for name, description, body in _DEFAULT_SKILLS:
                skills_store.write_skill(name, description, body)
        _GLOBAL_SKILLS_SEEDED_MARKER.write_text("seeded\n")


def _resolve_stack(stack_id: str) -> dict | None:
    if stack_id == _GLOBAL_STACK_ID:
        _ensure_global_seeded()
        return {"id": _GLOBAL_STACK_ID, "name": "Global (default)", "workdir": None, "is_global": True}
    return stacks_store.get(stack_id)


def _stack_agents_dir(stack: dict) -> Path:
    if stack.get("is_global"):
        return agents_store.AGENTS_DIR
    return agents_store.project_agents_dir(stack["workdir"])


def _other_active_agent_names(exclude: str | None, agents_dir=None) -> list[str]:
    return sorted(a.name for a in agents_store.list_agents(agents_dir=agents_dir) if a.name != exclude)


def _render_agent_form(agent, filename, agents_dir, back_url, back_label, save_action):
    if agent is None:
        base_tools_value, spawnable, exclude, selected_skills = "", [], None, []
    else:
        base_tools, spawnable = agents_store.parse_tools(agent.frontmatter.get("tools", ""))
        base_tools_value, exclude = ", ".join(base_tools), agent.name
        selected_skills = [s.strip() for s in agent.frontmatter.get("skills", "").split(",") if s.strip()]
    return render_template(
        "edit.html",
        agent=agent,
        filename=filename,
        base_tools_value=base_tools_value,
        spawnable=spawnable,
        other_agents=_other_active_agent_names(exclude, agents_dir=agents_dir),
        available_skills=skills_store.list_skills(),
        selected_skills=selected_skills,
        cli_providers=[p for p in providers.list_providers() if p.id != "claude"],
        provider_usable={p.id: providers.usable(p.id) for p in providers.list_providers()},
        back_url=back_url,
        back_label=back_label,
        save_action=save_action,
    )


def _save_agent_from_form(agents_dir):
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
    body = agents_store.strip_skills_block(body)

    selected_skill_names = request.form.getlist("skill_names")
    if selected_skill_names:
        available = {s.name: s for s in skills_store.list_skills()}
        selected_skills = [available[n] for n in selected_skill_names if n in available]
        if selected_skills:
            frontmatter["skills"] = ", ".join(s.name for s in selected_skills)
            body = agents_store.build_skills_block(selected_skills) + body

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

    agents_store.write_agent(filename, frontmatter, body, agents_dir=agents_dir)
    restarted = session_manager.restart_all_running()
    note = f" Restarted {len(restarted)} running session(s)." if restarted else ""
    flash(f"Saved {filename}.{note}", "success")


@app.get("/stacks/<stack_id>/agents/new")
@require_auth
def new_stack_agent_form(stack_id):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    return _render_agent_form(
        agent=None, filename=None, agents_dir=_stack_agents_dir(stack),
        back_url=url_for("edit_stack_form", stack_id=stack_id), back_label=f"back to {stack['name']}",
        save_action=url_for("save_stack_agent", stack_id=stack_id),
    )


@app.get("/stacks/<stack_id>/agents/<filename>/edit")
@require_auth
def edit_stack_agent_form(stack_id, filename):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    agents_dir = _stack_agents_dir(stack)
    try:
        agent = agents_store.read_agent(filename, agents_dir=agents_dir)
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("edit_stack_form", stack_id=stack_id))
    return _render_agent_form(
        agent=agent, filename=filename, agents_dir=agents_dir,
        back_url=url_for("edit_stack_form", stack_id=stack_id), back_label=f"back to {stack['name']}",
        save_action=url_for("save_stack_agent", stack_id=stack_id),
    )


@app.post("/stacks/<stack_id>/agents/save")
@require_auth
def save_stack_agent(stack_id):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    try:
        _save_agent_from_form(agents_dir=_stack_agents_dir(stack))
    except ValueError as exc:
        flash(f"Not saved: {exc}", "error")
    return redirect(url_for("edit_stack_form", stack_id=stack_id))


@app.post("/stacks/<stack_id>/agents/<filename>/delete")
@require_auth
def delete_stack_agent(stack_id, filename):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    agents_store.delete_agent(filename, agents_dir=_stack_agents_dir(stack))
    restarted = session_manager.restart_all_running()
    note = f" Restarted {len(restarted)} running session(s)." if restarted else ""
    flash(f"Deleted {filename}.{note}", "success")
    return redirect(url_for("edit_stack_form", stack_id=stack_id))


def _save_skill_from_form(existing_name):
    name = existing_name or request.form.get("name", "").strip()
    description = request.form.get("description", "")
    body = request.form.get("body", "")
    skills_store.write_skill(name, description, body)


@app.get("/skills")
@require_auth
def skills_page():
    return render_template("skills.html", skills=skills_store.list_skills())


@app.get("/skills/new")
@require_auth
def new_skill_form():
    return render_template(
        "skill_edit.html", skill=None, name=None,
        back_url=url_for("skills_page"), back_label="back to skills",
        save_action=url_for("save_skill"),
    )


@app.get("/skills/<name>/edit")
@require_auth
def edit_skill_form(name):
    try:
        skill = skills_store.read_skill(name)
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("skills_page"))
    return render_template(
        "skill_edit.html", skill=skill, name=name,
        back_url=url_for("skills_page"), back_label="back to skills",
        save_action=url_for("save_skill", existing_name=name),
    )


@app.post("/skills/save")
@require_auth
def save_skill():
    try:
        _save_skill_from_form(existing_name=request.args.get("existing_name"))
    except ValueError as exc:
        flash(f"Not saved: {exc}", "error")
    return redirect(url_for("skills_page"))


@app.post("/skills/<name>/delete")
@require_auth
def delete_skill_route(name):
    skills_store.delete_skill(name)
    flash(f"Deleted skill '{name}'.", "success")
    return redirect(url_for("skills_page"))


# ---- Agent stack presets ----


def _activate_selection(agents_dir) -> list[str]:
    """Shared by create/edit: activates whichever preset or library
    checkboxes were submitted into agents_dir. Returns filenames written."""
    preset_id = request.form.get("preset_id", "").strip()
    agent_ids = request.form.getlist("agent_ids")
    if preset_id:
        return presets.activate_preset(preset_id, agents_dir=agents_dir)
    if agent_ids:
        return presets.activate(agent_ids, agents_dir=agents_dir)
    return []


def _known_directories() -> list[str]:
    """Every directory Cadre already knows about -- existing sessions'
    workdirs and existing stacks' workdirs -- so pointing a new stack at
    an already-existing project doesn't mean typing/copying its path from
    memory. Purely a convenience list; any absolute path still works."""
    dirs = {s["workdir"] for s in sessions_store.list_sessions()}
    dirs |= {s["workdir"] for s in stacks_store.list_stacks()}
    return sorted(dirs)


@app.get("/stacks/new")
@require_auth
def new_stack_form():
    return render_template(
        "stack_form.html",
        stack=None,
        stack_presets=presets.list_presets(),
        library=presets.list_library_agents(),
        active_names=set(),
        default_base=str(settings.projects_root() / "agent-stacks"),
        known_dirs=_known_directories(),
        prefill_name=request.args.get("name", ""),
        prefill_workdir=request.args.get("workdir", ""),
    )


@app.post("/stacks/new")
@require_auth
def create_stack():
    name = request.form.get("name", "").strip()
    workdir = request.form.get("workdir", "").strip()
    if not name or not workdir:
        flash("Name and directory are both required.", "error")
        return redirect(url_for("new_stack_form"))
    path = Path(workdir).expanduser()
    if not path.is_absolute():
        flash("Directory must be an absolute path, e.g. /home/you/agent-stacks/coding.", "error")
        return redirect(url_for("new_stack_form"))
    path.mkdir(parents=True, exist_ok=True)

    try:
        written = _activate_selection(agents_store.project_agents_dir(str(path)))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("new_stack_form"))

    stacks_store.add(name, str(path))
    flash(f"Created stack '{name}' with {len(written)} agent(s).", "success")
    return redirect(url_for("index"))


@app.get("/stacks/<stack_id>/edit")
@require_auth
def edit_stack_form(stack_id):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    agents_dir = _stack_agents_dir(stack)
    stack_agents = agents_store.list_agents(agents_dir=agents_dir)
    active_names = {a.name for a in stack_agents}
    return render_template(
        "stack_form.html",
        stack=stack,
        stack_agents=stack_agents,
        stack_presets=presets.list_presets(),
        library=presets.list_library_agents(),
        active_names=active_names,
        default_base=str(settings.projects_root() / "agent-stacks"),
        known_dirs=_known_directories(),
    )


@app.post("/stacks/<stack_id>/edit")
@require_auth
def edit_stack(stack_id):
    if stack_id == _GLOBAL_STACK_ID:
        try:
            written = _activate_selection(agents_store.AGENTS_DIR)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("edit_stack_form", stack_id=stack_id))
        if written:
            session_manager.restart_all_running()
        note = f"Activated {len(written)} agent(s)." if written else "Nothing selected to activate."
        flash(note, "success")
        return redirect(url_for("index"))

    stack = stacks_store.get(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))

    name = request.form.get("name", "").strip()
    workdir = request.form.get("workdir", "").strip()
    if not name or not workdir:
        flash("Name and directory are both required.", "error")
        return redirect(url_for("edit_stack_form", stack_id=stack_id))
    path = Path(workdir).expanduser()
    if not path.is_absolute():
        flash("Directory must be an absolute path.", "error")
        return redirect(url_for("edit_stack_form", stack_id=stack_id))
    path.mkdir(parents=True, exist_ok=True)

    try:
        written = _activate_selection(agents_store.project_agents_dir(str(path)))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("edit_stack_form", stack_id=stack_id))

    stacks_store.update(stack_id, name=name, workdir=str(path))

    if written:
        matching_session = next((s for s in sessions_store.list_sessions() if s["workdir"] == str(path)), None)
        if matching_session:
            session_manager.restart(matching_session["id"])

    note = f", activated {len(written)} agent(s)" if written else ""
    flash(f"Saved '{name}'{note}.", "success")
    return redirect(url_for("index"))


@app.post("/stacks/<stack_id>/delete")
@require_auth
def delete_stack(stack_id):
    stack = stacks_store.get(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    if request.form.get("wipe_agents") == "on":
        agents_dir = agents_store.project_agents_dir(stack["workdir"])
        if agents_dir.exists():
            shutil.rmtree(agents_dir)
    stacks_store.remove(stack_id)
    flash(f"Deleted stack '{stack['name']}'.", "success")
    return redirect(url_for("index"))


def _render_diagram(agents_dir, heading, back_url, back_label, save_action):
    active = agents_store.list_agents(agents_dir=agents_dir)
    nodes = []
    for a in active:
        base_tools, spawnable = agents_store.parse_tools(a.frontmatter.get("tools", ""))
        nodes.append(
            {
                "filename": a.filename,
                "name": a.name,
                "spawnable": spawnable,
                "others": [o.name for o in active if o.name != a.name],
                "primary_provider": a.frontmatter.get("primary_provider", "claude"),
            }
        )
    return render_template(
        "stacks_diagram.html",
        nodes=nodes,
        heading=heading,
        back_url=back_url,
        back_label=back_label,
        save_action=save_action,
    )


def _apply_spawnable(agents_dir) -> None:
    filename = request.form.get("agent_filename", "")
    can_spawn = request.form.getlist("can_spawn")
    agent = agents_store.read_agent(filename, agents_dir=agents_dir)
    base_tools, _old_spawnable = agents_store.parse_tools(agent.frontmatter.get("tools", ""))
    frontmatter = dict(agent.frontmatter)
    tools_value = agents_store.serialize_tools(base_tools, can_spawn)
    if tools_value:
        frontmatter["tools"] = tools_value
    else:
        frontmatter.pop("tools", None)
    agents_store.write_agent(filename, frontmatter, agent.body, agents_dir=agents_dir)
    session_manager.restart_all_running()


@app.get("/stacks/<stack_id>/diagram")
@require_auth
def stack_diagram(stack_id):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    return _render_diagram(
        agents_dir=_stack_agents_dir(stack),
        heading=f"{stack['name']} diagram",
        back_url=url_for("edit_stack_form", stack_id=stack_id),
        back_label=f"back to {stack['name']}",
        save_action=url_for("stack_set_spawnable", stack_id=stack_id),
    )


@app.post("/stacks/<stack_id>/diagram/set-spawnable")
@require_auth
def stack_set_spawnable(stack_id):
    stack = _resolve_stack(stack_id)
    if stack is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("index"))
    try:
        _apply_spawnable(agents_dir=_stack_agents_dir(stack))
    except (ValueError, FileNotFoundError) as exc:
        flash(str(exc), "error")
    return redirect(url_for("stack_diagram", stack_id=stack_id))


# ---- Server-side directory browser (a browser file picker can't hand a
# web page a real filesystem path -- this walks the filesystem here, on
# the same machine the paths actually refer to) ----


@app.get("/api/browse-dirs")
@require_auth
def browse_dirs():
    raw = request.args.get("path", "").strip() or str(Path.home())
    try:
        target = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        return {"ok": False, "error": f"Invalid path: {exc}"}
    if not target.exists():
        return {"ok": False, "error": f"'{target}' doesn't exist."}
    if not target.is_dir():
        target = target.parent
    try:
        entries = sorted(
            (p for p in target.iterdir() if p.is_dir()),
            key=lambda p: p.name.lower(),
        )
    except PermissionError:
        return {"ok": False, "error": f"Permission denied reading '{target}'."}
    parent = str(target.parent) if target.parent != target else None
    return {
        "ok": True,
        "path": str(target),
        "parent": parent,
        "dirs": [{"name": p.name, "path": str(p)} for p in entries],
    }


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
        default_provider=settings.get("default_provider"),
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

GITHUB_REPO = "bburge14/cadre"


def _read_version() -> str:
    try:
        return (config.BASE_DIR / "VERSION").read_text().strip()
    except FileNotFoundError:
        return "unknown"


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
        claude_installed=providers.binary_found("claude"),
        claude_logged_in=providers.claude_logged_in(),
        provider_binaries={p.id: providers.binary_found(p.id) for p in providers.list_providers()},
        current_version=_read_version(),
        github_repo_url=f"https://github.com/{GITHUB_REPO}",
        default_provider=settings.get("default_provider"),
        orchestration_candidates=providers.orchestration_candidates(),
        cli_providers=[p for p in providers.list_providers() if p.id != "claude"],
    )


@app.get("/settings/check-update")
@require_auth
def check_update():
    current = _read_version()
    try:
        latest = _fetch_latest_release().get("tag_name", "").lstrip("v")
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": str(exc), "current": current}
    return {
        "ok": True,
        "current": current,
        "latest": latest,
        "up_to_date": latest == current,
        "release_url": f"https://github.com/{GITHUB_REPO}/releases/tag/v{latest}",
    }


def _matching_dashboard_service() -> str | None:
    """Whether *this exact checkout* owns a registered dashboard
    service/task -- same WorkingDirectory-match safety check as the
    uninstall/update scripts, reimplemented here since this runs from
    inside the app rather than a shell script. Only ever looks at the
    dashboard service, never the daemon -- restarting the daemon ends live
    Claude Code sessions, which this feature must never do unprompted."""
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["schtasks", "/Query", "/TN", "Cadre-App", "/V", "/FO", "LIST"],
                capture_output=True, text=True, timeout=10,
            )
            if out.returncode != 0:
                return None
            for line in out.stdout.splitlines():
                if line.strip().startswith("Start In:"):
                    work_dir = line.split(":", 1)[1].strip()
                    if Path(work_dir) == config.BASE_DIR:
                        return "Cadre-App"
        except (OSError, subprocess.SubprocessError):
            return None
        return None

    service_file = Path.home() / ".config" / "systemd" / "user" / "cadre-app.service"
    if not service_file.exists():
        return None
    try:
        for line in service_file.read_text().splitlines():
            if line.startswith("WorkingDirectory="):
                raw = line.split("=", 1)[1].strip()
                resolved = Path(raw.replace("%h", str(Path.home()), 1))
                if resolved == config.BASE_DIR:
                    return "cadre-app.service"
    except OSError:
        return None
    return None


def _fetch_latest_release() -> dict:
    resp = requests.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _apply_zip_update(log_parts: list[str]) -> dict | None:
    """Fetches the latest release's source zipball and copies it over this
    install -- the path for a ZIP-downloaded (no .git) instance, which
    can't git pull. Returns None on success (log_parts updated in place),
    or an error dict to return immediately."""
    try:
        release = _fetch_latest_release()
        zip_url = release["zipball_url"]
        tag = release.get("tag_name", "?")
    except (requests.RequestException, ValueError, KeyError) as exc:
        return {"ok": False, "error": f"Couldn't look up the latest release: {exc}"}

    log_parts.append(f"Downloading {tag} from GitHub...")
    try:
        zresp = requests.get(zip_url, timeout=60)
        zresp.raise_for_status()
    except requests.RequestException as exc:
        return {"ok": False, "error": f"Download failed: {exc}", "log": "\n".join(log_parts)}

    tmp_dir = Path(tempfile.mkdtemp(prefix="cadre-update-"))
    try:
        zip_path = tmp_dir / "update.zip"
        zip_path.write_bytes(zresp.content)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)
        zip_path.unlink()

        # GitHub's source zipball always has exactly one top-level
        # directory (owner-repo-shortsha).
        subdirs = [p for p in tmp_dir.iterdir() if p.is_dir()]
        if len(subdirs) != 1:
            return {
                "ok": False,
                "error": f"Unexpected archive layout ({len(subdirs)} top-level entries).",
                "log": "\n".join(log_parts),
            }

        log_parts.append(f"Copying files into {config.BASE_DIR}...")
        # dirs_exist_ok=True merges into the existing directory rather than
        # requiring an empty destination -- and since venv/, instance/,
        # and .env never exist in a fresh release zipball, this can only
        # add/overwrite tracked files, never touch local state, same
        # guarantee git pull already gives on the git-checkout path.
        shutil.copytree(subdirs[0], config.BASE_DIR, dirs_exist_ok=True)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"ok": False, "error": f"Extracting/copying the update failed: {exc}", "log": "\n".join(log_parts)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    log_parts.append("Files updated.")
    return None


def _apply_update() -> dict:
    log_parts = []

    def _run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            args, cwd=config.BASE_DIR, capture_output=True, text=True, timeout=120,
        )

    if (config.BASE_DIR / ".git").is_dir():
        try:
            pull = _run(["git", "pull"])
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"git pull failed to run: {exc}"}
        log_parts.append("$ git pull\n" + pull.stdout + pull.stderr)
        if pull.returncode != 0:
            return {"ok": False, "error": "git pull failed -- see log.", "log": "\n".join(log_parts)}
    else:
        error = _apply_zip_update(log_parts)
        if error is not None:
            return error

    pip_path = config.BASE_DIR / ("venv/Scripts/pip.exe" if sys.platform == "win32" else "venv/bin/pip")
    try:
        deps = _run([str(pip_path), "install", "-r", "requirements.txt"])
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"dependency install failed to run: {exc}", "log": "\n".join(log_parts)}
    log_parts.append("$ pip install -r requirements.txt\n" + deps.stdout + deps.stderr)
    if deps.returncode != 0:
        return {"ok": False, "error": "Dependency install failed -- see log.", "log": "\n".join(log_parts)}

    return {"ok": True, "log": "\n".join(log_parts), "restart_target": _matching_dashboard_service()}


def _restart_dashboard_service(service_name: str) -> None:
    """Runs in a background thread, after the HTTP response for
    apply_update has already been sent -- restarting the service that's
    serving this very request kills the process handling it, so this can't
    happen synchronously inside the request."""
    time.sleep(1.5)
    try:
        if sys.platform == "win32":
            subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-ScheduledTask -TaskName '{service_name}'; Start-Sleep -Seconds 1; Start-ScheduledTask -TaskName '{service_name}'"], timeout=30)
        else:
            subprocess.run(["systemctl", "--user", "restart", service_name], timeout=30)
    except (OSError, subprocess.SubprocessError):
        pass


@app.post("/settings/apply-update")
@require_auth
def apply_update():
    result = _apply_update()
    if not result["ok"]:
        return result
    restart_target = result.pop("restart_target", None)
    if restart_target:
        threading.Thread(target=_restart_dashboard_service, args=(restart_target,), daemon=True).start()
        result["restarting"] = True
    else:
        result["restarting"] = False
    return result


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

    default_provider = request.form.get("default_provider", "")
    if default_provider:
        if default_provider not in {p.id for p in providers.orchestration_candidates()}:
            flash("That provider can't be set as the default -- it isn't connected, or can't run Agent Stacks.", "error")
            return redirect(url_for("settings_form"))
        fields["default_provider"] = default_provider

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
    matching_stack = next(
        (s for s in stacks_store.list_stacks() if s["workdir"] == entry["workdir"]), None
    )
    return render_template(
        "session_detail.html",
        session=entry,
        status=session_manager.status(session_id),
        matching_stack=matching_stack,
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
