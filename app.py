from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import croniter
import requests
from flask import Flask, flash, redirect, render_template, request, session, url_for

import agent_formats
import agents_store
import auth
import config
import git_hosts
import integrations_store
import network_info
import presets
import providers
import session_manager
import sessions_store
import settings
import skills_store
import stacks_store
import terminal_theme
import workflows_store
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


@app.after_request
def _disable_html_caching(response):
    # Static assets (style.css, terminal.js, etc.) are cache-busted with
    # a ?v={{ asset_version }} query string, but that only works if the
    # HTML page embedding those URLs is itself fresh -- a cached HTML
    # response keeps citing whatever version string was current when it
    # was cached, forever, which defeats the whole mechanism. Browsers
    # apply their own default caching heuristics to any response with no
    # explicit Cache-Control header, which can be surprisingly long-lived
    # for a plain page with no other caching signal. Force every HTML
    # response to always revalidate so a page reload can never silently
    # serve stale markup pointing at a stale asset version.
    if response.content_type and response.content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": auth.csrf_token}


@app.context_processor
def inject_dashboard_theme():
    return {"dashboard_theme": settings.get("dashboard_theme")}


# (value, label) -- value must match a key in static/terminal.js's
# XTERM_THEMES and, for "auto", the special-cased branch in
# resolveXtermTheme(). Kept here (not just inline in the two templates
# that build a <select> from it) so both stay in sync automatically.
TERMINAL_THEME_OPTIONS = [
    ("auto", "Auto"), ("dark", "Dark"), ("light", "Light"),
    ("dracula", "Dracula"), ("solarized-dark", "Solarized Dark"), ("solarized-light", "Solarized Light"),
    ("nord", "Nord"), ("monokai", "Monokai"), ("gruvbox-dark", "Gruvbox Dark"),
    ("tokyo-night", "Tokyo Night"), ("one-dark", "One Dark"),
    ("catppuccin-mocha", "Catppuccin Mocha"), ("synthwave", "Synthwave"), ("matrix", "Matrix"),
    ("ayu-dark", "Ayu Dark"), ("github-dark", "GitHub Dark"), ("cyberpunk", "Cyberpunk"),
    ("rose-quartz", "Rose Quartz"), ("deep-forest", "Deep Forest"), ("abyssal", "Abyssal"),
    ("sunset-blvd", "Sunset Blvd"), ("arctic-frost", "Arctic Frost"), ("blood-moon-term", "Blood Moon"),
]


@app.context_processor
def inject_terminal_theme():
    return {"terminal_theme": settings.get("terminal_theme"), "terminal_theme_options": TERMINAL_THEME_OPTIONS}


# Values must match an `html[data-theme="..."]` block in static/style.css.
# Kept as one list (not just inline in save_settings()'s membership check)
# so a new theme card in settings.html and its acceptance here can't drift
# out of sync the way the old inline 7-item tuple already had before this
# batch of 12 new ones.
DASHBOARD_THEME_VALUES = {
    "default", "circuit", "slate", "light", "ocean", "volcanic", "amethyst",
    "forest", "neon-city", "blood-moon", "frost", "desert", "toxic",
    "galaxy", "aurora", "code-rain", "ember", "sakura", "deep-space", "rain", "lava-lamp", "drip",
    "code-rain-cyber", "code-rain-crimson", "code-rain-gold", "code-rain-violet", "code-rain-ice",
    "rain-violet", "rain-acid", "rain-crimson", "rain-neon", "rain-ash",
    "lava-lamp-cosmic", "lava-lamp-toxic",
    "drip-venom", "drip-blood", "drip-tar", "drip-acid", "drip-mercury",
    "circuit-amber", "circuit-blue", "circuit-crimson",
}


def _static_asset_version() -> str:
    """A browser caches style.css aggressively by default, with nothing
    telling it a CSS-only change (no template/route change) means the
    URL's content is now stale -- this is exactly what made the Galaxy
    theme "only work on Settings" (that page happened to get a fresh
    fetch from the form POST/redirect; other already-open tabs kept
    serving the old cached CSS). Appending this as a query string on
    style.css's URL means any CSS change gets a new URL automatically,
    busting the cache without needing a manual hard-refresh."""
    try:
        return str(int((config.BUNDLE_DIR / "static" / "style.css").stat().st_mtime))
    except OSError:
        return "0"


_STATIC_ASSET_VERSION = _static_asset_version()


@app.context_processor
def inject_asset_version():
    return {"asset_version": _STATIC_ASSET_VERSION}


@app.before_request
def enforce_csrf():
    # setup/login/forgot_password are all pre-authentication -- their
    # real protection is verify_login()/reset_password_via_security()'s
    # own rate limiting, not a session-bound CSRF token (which a CSRF
    # attack against a logged-out visitor wouldn't gain anything from
    # bypassing anyway, since there's no authenticated session to abuse).
    if request.method == "POST" and request.endpoint not in ("setup", "login", "forgot_password"):
        auth.check_csrf()


def _sessions_with_status() -> list[dict]:
    sessions = []
    for entry in sessions_store.list_sessions():
        if entry.get("internal"):
            continue
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
    security_question = request.form.get("security_question", "").strip()
    security_answer = request.form.get("security_answer", "").strip()
    if not username or not password:
        flash("Username and password are both required.", "error")
        return redirect(url_for("setup_form"))
    if password != confirm:
        flash("Passwords didn't match.", "error")
        return redirect(url_for("setup_form"))
    if len(password) < 8:
        flash("Password should be at least 8 characters.", "error")
        return redirect(url_for("setup_form"))
    if not security_question or not security_answer:
        flash("A security question and answer are both required -- it's the only way back in if you forget your password and don't have terminal access to this machine.", "error")
        return redirect(url_for("setup_form"))
    auth.create_admin(username, password, security_question, security_answer)
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


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if not auth.admin_exists():
        return redirect(url_for("setup_form"))

    username = ""
    question = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()

        if "answer" in request.form:
            # Step 2: answer + new password submitted together.
            answer = request.form.get("answer", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            question = auth.get_security_question(username)  # re-derive to redisplay step 2 on error

            if not new_password or new_password != confirm_password:
                flash("New password and confirmation didn't match.", "error")
            elif len(new_password) < 8:
                flash("New password should be at least 8 characters.", "error")
            else:
                ok, error = auth.reset_password_via_security(username, answer, new_password)
                if ok:
                    flash("Password reset -- log in with your new password.", "success")
                    return redirect(url_for("login_form"))
                flash(error, "error")
        else:
            # Step 1: just the username, deciding whether to reveal the question.
            question = auth.get_security_question(username)
            if not question:
                flash(
                    "No recovery question is set for that account (or it "
                    "doesn't exist). If you have terminal access to this "
                    "machine, run the reset-admin script for your OS instead.",
                    "error",
                )

    return render_template("forgot_password.html", username=username, question=question)


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
        current_host=config.HOST,
        tailscale=network_info.tailscale_status(),
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
_GLOBAL_STACK_ID = stacks_store.GLOBAL_STACK_ID
_GLOBAL_SEEDED_MARKER = config.INSTANCE_DIR / "global_seeded"
_GLOBAL_SKILLS_SEEDED_MARKER = config.INSTANCE_DIR / "global_skills_seeded"  # legacy, pre-per-name tracking
_SKILLS_SEEDED_FILE = config.INSTANCE_DIR / "skills_seeded.json"

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
    (
        "code-review-checklist",
        "Checklist for reviewing a code change before calling it done -- "
        "correctness, edge cases, tests, security, readability. Use "
        "before finishing any change, whether reviewing your own work or "
        "another agent's.",
        "Correctness first: does it actually do what was asked, and does "
        "it handle the edge cases (empty input, null/None, the boundary "
        "values) not just the happy path. Check for tests -- a change "
        "with no way to verify it stays correct later is incomplete, not "
        "just under-polished. Scan for the obvious security classes: "
        "injection (SQL, command, XSS), secrets committed in code, "
        "missing auth checks on a new endpoint. Readability: would "
        "someone unfamiliar with this change understand it from the code "
        "and names alone, without needing the PR description. Flag scope "
        "creep -- unrelated changes bundled into the same diff make it "
        "harder to review and harder to revert independently.",
    ),
    (
        "test-writing-guidelines",
        "Guidelines for writing tests that actually catch regressions -- "
        "structure, naming, what to cover. Use when adding or reviewing "
        "test coverage for a change.",
        "One behavior per test, named so the failure message alone tells "
        "you what broke (`test_empty_cart_returns_zero_total`, not "
        "`test_cart_2`). Arrange-act-assert structure: set up state, "
        "perform the action, assert the outcome -- don't interleave them. "
        "Cover edge cases deliberately (empty/null input, boundary "
        "values, the error path), not just one happy-path case per "
        "function. Don't over-mock -- a test that mocks so much it only "
        "verifies the mocks were called, not that the real logic works, "
        "gives false confidence. Prefer testing behavior/output over "
        "internal implementation details, so a refactor that preserves "
        "behavior doesn't force every test to be rewritten.",
    ),
    (
        "error-handling-philosophy",
        "Reference for when to validate/handle errors versus trust "
        "internal guarantees. Use when writing code that could fail or "
        "receive bad input.",
        "Validate at system boundaries -- user input, external API "
        "responses, file/network I/O -- since those are where genuinely "
        "unpredictable data enters. Trust internal code and already-"
        "validated data; re-checking things the type system or a prior "
        "validation step already guarantees is noise, not safety. Fail "
        "loudly and early rather than swallowing an exception and "
        "continuing in a corrupted state -- a silent `except: pass` "
        "usually turns an obvious bug into a mysterious one discovered "
        "much later. Error messages should say what actually went wrong "
        "and where, specific enough to act on, not a generic \"something "
        "went wrong.\"",
    ),
    (
        "security-review-checklist",
        "Checklist for the most common vulnerability classes to check "
        "for before shipping code that handles input, auth, or external "
        "data. Use for any change touching user input, authentication, "
        "or a public-facing surface.",
        "Injection: SQL (parameterize, never string-concatenate user "
        "input into a query), command (avoid shelling out with "
        "unsanitized input), XSS (escape/sanitize anything rendered from "
        "user-controlled data). Auth: does a new endpoint/action actually "
        "check the caller is allowed to do this, not just that they're "
        "logged in. Secrets: no API keys, passwords, or tokens committed "
        "in code, ever -- config/env vars or a secrets store instead. "
        "Input validation: don't trust client-side validation alone, "
        "re-check on the server. Dependencies: a new package is a new "
        "trust boundary -- worth a second look for anything obscure or "
        "with broad permissions/network access.",
    ),
    (
        "dependency-upgrade-checklist",
        "Checklist for safely bumping a dependency version. Use before "
        "upgrading a library/package, not just after something breaks.",
        "Read the actual changelog/release notes between the current and "
        "target version, not just the target version's -- a multi-"
        "version jump can span several breaking changes. Check for a "
        "major-version bump specifically (semver breaking-change signal) "
        "and search the project for usages of anything the changelog "
        "flags as changed/removed. Run the existing test suite before "
        "and after -- a passing suite after the bump is the real "
        "confirmation, not just \"it installed cleanly.\" Upgrade one "
        "dependency (or one tightly-related group) at a time when "
        "multiple need bumping, so a regression is traceable to a "
        "specific change instead of a batch of them.",
    ),
    (
        "api-design-consistency",
        "Reference for keeping an API's shape consistent with itself -- "
        "naming, status codes, pagination, versioning. Use when adding "
        "or changing an API endpoint.",
        "Match the existing API's conventions before inventing new ones -- "
        "naming style (plural nouns for collections, consistent casing), "
        "how errors are shaped, how pagination/filtering already works "
        "elsewhere in the same API. Use status codes for what they "
        "actually mean (400 for a client-side validation error, 404 for "
        "genuinely missing, 401 vs 403 for auth vs. permission, not 200 "
        "with an error field buried in the body). Breaking an existing "
        "response shape needs a version bump or a new field, not a "
        "silent change to what callers already depend on. Keep "
        "request/response payloads only as large as needed -- don't "
        "return an entire object graph when a caller asked for one field.",
    ),
    (
        "accessibility-checklist",
        "Checklist for basic web accessibility -- semantic HTML, "
        "keyboard nav, contrast, labels. Use when building or reviewing "
        "any user-facing UI.",
        "Semantic HTML first (`button` not a clickable `div`, real "
        "heading levels, `label` tied to its input) -- most a11y comes "
        "free from using the right element instead of reimplementing its "
        "behavior. Everything interactive must be reachable and "
        "operable by keyboard alone (tab order, visible focus state, no "
        "mouse-only interactions). Images need real alt text (empty "
        "alt=\"\" only for genuinely decorative images, never a missing "
        "attribute). Check color contrast for text against its "
        "background, and never rely on color alone to convey state (a "
        "red border also needs an icon/text, for colorblind users). "
        "Don't add ARIA attributes to patch over non-semantic markup -- "
        "fix the markup first; ARIA is for cases plain HTML genuinely "
        "can't express.",
    ),
    (
        "sql-query-review",
        "Checklist for reviewing a SQL query for safety and performance "
        "before running it against real data. Use when writing or "
        "reviewing a non-trivial query.",
        "Never string-concatenate user input into a query -- parameterize "
        "every value, no exceptions. Avoid `SELECT *` in code that ships "
        "(schema changes silently change what's returned); name the "
        "columns actually needed. Check that a query touching a large "
        "table is actually index-aware -- a `WHERE` clause on an "
        "unindexed column, or a function wrapped around an indexed "
        "column, can silently force a full table scan. For anything "
        "that mutates data at scale, know the row count it'll affect "
        "before running it, and prefer a transaction you can roll back "
        "over a bare `UPDATE`/`DELETE` against production.",
    ),
    (
        "infrastructure-change-safety",
        "Checklist for applying an infrastructure change safely -- plan "
        "review, blast radius, rollback. Use before applying any "
        "infrastructure-as-code change, especially to shared/production "
        "resources.",
        "Always review the plan/diff output before applying -- know "
        "exactly what will be created, changed, or destroyed, especially "
        "anything showing as destroy-and-recreate for a stateful "
        "resource (that usually means data loss, not just downtime). "
        "Assess blast radius: a change to a shared VPC, IAM policy, or "
        "database affects everything downstream of it, not just the "
        "resource named in the diff. Have a rollback plan before "
        "applying, not after something breaks -- know how to revert this "
        "specific change. Avoid manual out-of-band changes to "
        "infrastructure the IaC tool manages -- they cause state drift "
        "that silently breaks the next real apply.",
    ),
    (
        "runbook-format",
        "Structure for writing an operational runbook -- a step-by-step "
        "procedure for a recurring or emergency task. Use when "
        "documenting a procedure someone (or another agent) will need to "
        "follow under time pressure later.",
        "Lead with what this runbook is for and when to use it -- the "
        "specific symptom or trigger, not a vague title. Numbered steps, "
        "one action per step, each one concrete enough to execute "
        "without interpretation (the exact command, not \"restart the "
        "service\"). Call out anything destructive or hard to reverse "
        "explicitly, before the step, not after. Include how to verify "
        "each major step actually worked, not just that it ran without "
        "erroring. Note prerequisites (access, tools, who to page) up "
        "front so they're not discovered mid-incident.",
    ),
    (
        "incident-postmortem-format",
        "Structure for a blameless incident postmortem -- timeline, "
        "impact, root cause, action items. Use after resolving a "
        "production incident, not while it's still ongoing.",
        "Blameless: describe what happened and why the system/process "
        "allowed it, never who made a mistake -- language like \"X "
        "incorrectly did Y\" gets rewritten to what about the system let "
        "that happen. Factual timeline first (when it started, when it "
        "was detected, key actions, when it was resolved), stated in the "
        "actual timezone/timestamps used, before any narrative. State "
        "impact concretely (what was affected, for how long, who "
        "noticed) rather than vaguely. Root cause, not just the nearest "
        "symptom -- and distinguish contributing factors from the actual "
        "cause. End with specific, assigned, verifiable action items -- "
        "\"improve monitoring\" isn't one; \"add an alert on X exceeding "
        "Y\" is.",
    ),
    (
        "data-validation-checklist",
        "Checklist for sanity-checking data before trusting it -- null "
        "rates, duplicates, schema drift, row counts. Use before relying "
        "on a dataset or pipeline output for anything downstream.",
        "Check null/missing rates on columns that shouldn't have them, "
        "not just that the pipeline ran without erroring. Check for "
        "duplicate keys where uniqueness is assumed -- a silent join "
        "fan-out from an unexpected duplicate is one of the most common "
        "ways bad numbers happen. Compare row counts against a sane "
        "expectation (roughly matching the prior run, or the known size "
        "of the source) to catch a silently truncated or doubled load. "
        "Watch for schema drift -- a column that changed type, got "
        "renamed, or disappeared upstream, which breaks assumptions "
        "without necessarily erroring. State the actual data freshness "
        "(as of when) rather than assuming it's current.",
    ),
    (
        "notebook-hygiene",
        "Reference for keeping a data-science notebook reproducible and "
        "reviewable. Use when working in or reviewing a Jupyter/similar "
        "notebook.",
        "Clear cell outputs before committing -- a committed notebook "
        "full of stale outputs (and the diff noise they cause) is a "
        "common source of confusion about what's actually current. "
        "Before calling a notebook done, restart the kernel and run it "
        "top to bottom -- out-of-order execution during exploration "
        "hides state that won't reproduce for anyone else. Extract logic "
        "that's actually reused (or that belongs in production) into a "
        "real module instead of copy-pasted across cells/notebooks. Keep "
        "exploration and the final, presentable analysis separate -- "
        "don't make a reader wade through every dead-end you tried.",
    ),
    (
        "bug-report-reproduction-steps",
        "How to write a minimal, reproducible bug report when escalating "
        "something you can't fix yourself. Use when handing off a bug "
        "you've investigated but not resolved.",
        "Lead with the actual observed behavior versus the expected "
        "behavior, stated concretely, not \"it doesn't work.\" Give the "
        "smallest set of steps that reliably reproduces it -- strip out "
        "anything not actually necessary to trigger the bug. Include the "
        "real error/stack trace/log output verbatim, not a paraphrase of "
        "it. State what you already ruled out and why, so whoever picks "
        "this up doesn't repeat your first hour of investigation. Note "
        "environment/version specifics if there's any chance the bug is "
        "specific to one -- a bug that only reproduces on one OS/version "
        "combination is a different, more useful report than an "
        "unqualified \"this is broken.\"",
    ),
    (
        "fact-checking-checklist",
        "Checklist for verifying claims before publishing anything meant "
        "to be read as factual. Use before finishing a piece that states "
        "numbers, dates, or claims about the world.",
        "Every specific number, date, or attributed claim should trace "
        "back to an actual source you looked at, not something that "
        "sounds right. Flag anything you couldn't verify explicitly "
        "rather than smoothing over the gap with confident-sounding "
        "language. Distinguish fact from opinion/interpretation clearly "
        "in the writing itself -- a reader shouldn't have to guess which "
        "is which. For anything time-sensitive, confirm it's still "
        "current as of when this is being published, not just when the "
        "source was originally found.",
    ),
    (
        "outline-before-drafting",
        "Why and how to sketch structure before writing prose. Use "
        "before starting a first draft of anything longer than a couple "
        "of paragraphs.",
        "Sketch the actual structure first -- the sections/beats in "
        "order, and the one main point each should land -- before "
        "writing full sentences. Identify the core argument or takeaway "
        "up front; a piece written to discover its point as it goes "
        "usually needs a heavier rewrite than one planned around a clear "
        "thesis. Order for the reader's understanding, not the order "
        "ideas occurred to you -- what do they need to know first for "
        "the rest to land. A rough outline that gets restructured before "
        "drafting is far cheaper than restructuring finished prose.",
    ),
    (
        "presentation-of-findings",
        "How to present research or data findings so the actual point "
        "isn't buried. Use when writing up results/findings for someone "
        "else to act on.",
        "Lead with the takeaway, not the methodology -- state what was "
        "found and what it means before walking through how you got "
        "there. Visualize only when it clarifies something prose can't "
        "convey easily (a real trend, a comparison) -- a chart that "
        "just restates one number is decoration, not insight. Make the "
        "confidence level explicit (well-supported by multiple sources "
        "vs. a single thin data point) instead of presenting every "
        "finding with the same certainty. State what would change the "
        "conclusion, if anything -- it signals you've actually stress-"
        "tested the finding rather than just reported the first result "
        "that came back.",
    ),
]


def _ensure_default_skills_seeded() -> None:
    """Adds each _DEFAULT_SKILLS entry the *first* time it's introduced,
    tracked by name (instance/skills_seeded.json) rather than a single
    one-shot marker -- so growing this list later (as just happened: 3 ->
    20) actually reaches existing installs instead of silently doing
    nothing because "skills were already seeded once" no longer means
    "every current default has been offered." A name already recorded as
    seeded is never re-added even if the user deleted it since -- that's
    still respected, just per-skill instead of all-or-nothing."""
    seeded_names: set[str] = set()
    if _SKILLS_SEEDED_FILE.exists():
        seeded_names = set(json.loads(_SKILLS_SEEDED_FILE.read_text()))
    elif _GLOBAL_SKILLS_SEEDED_MARKER.exists():
        # Migrating from the old all-or-nothing marker: the 3 skills that
        # existed back then already had their one shot (respect any the
        # user has since deleted); everything added after is still new.
        seeded_names = {"commit-message-style", "writing-tone-guide", "research-source-checklist"}

    existing_names = {s.name for s in skills_store.list_skills()}
    newly_seeded = False
    for name, description, body in _DEFAULT_SKILLS:
        if name in seeded_names:
            continue
        if name not in existing_names:
            skills_store.write_skill(name, description, body)
        seeded_names.add(name)
        newly_seeded = True

    if newly_seeded or not _SKILLS_SEEDED_FILE.exists():
        _SKILLS_SEEDED_FILE.write_text(json.dumps(sorted(seeded_names), indent=2))


_PRESET_AGENTS_SKILLS_MIGRATED_MARKER = config.INSTANCE_DIR / "preset_agents_skills_migrated"


def _ensure_existing_preset_agents_get_default_skills() -> None:
    """One-time catch-up for agents that were already on disk before
    per-agent default-skill attachment existed -- that only happens at
    activation time (presets.activate()), so an agent created before this
    feature shipped never got the chance. Runs once (its own marker, not
    reused for anything else); only touches an agent that's (a) named
    after a known preset template and (b) doesn't already have skills of
    its own set, so anything hand-customized since is left alone."""
    if _PRESET_AGENTS_SKILLS_MIGRATED_MARKER.exists():
        return

    agents_dirs = [agents_store.AGENTS_DIR]
    agents_dirs.extend(agents_store.project_agents_dir(s["workdir"]) for s in stacks_store.list_stacks())

    for agents_dir in agents_dirs:
        for agent in agents_store.list_agents(agents_dir=agents_dir):
            agent_id = agent.filename.removesuffix(".md")
            if agent_id not in presets.AGENT_SKILL_HINTS:
                continue
            if agent.frontmatter.get("skills", "").strip():
                continue
            frontmatter, body = presets.attach_default_skills(agent_id, dict(agent.frontmatter), agent.body)
            if frontmatter.get("skills"):
                agents_store.write_agent(agent.filename, frontmatter, body, agents_dir=agents_dir)
                _sync_agent_formats(agents_dir, agent.filename)

    _PRESET_AGENTS_SKILLS_MIGRATED_MARKER.write_text("done\n")


def _ensure_global_seeded() -> None:
    """The default stack shouldn't just be empty scaffolding -- seed it
    with the Generalist preset the first time it's ever found empty, so a
    fresh install (or one that's simply never had anything activated into
    ~/.claude/agents/ yet) has something in it out of the box. Runs once
    -- marked via a sentinel file so deliberately clearing it out later
    doesn't cause it to keep coming back. Skills get their own independent
    seeding (not gated behind the same marker as agents) since they're an
    unrelated concern that can legitimately still be empty even after
    agents have already been seeded or hand-populated."""
    # Skills seeded before the Generalist preset activates below (not
    # just before agents are seeded) -- presets.activate() attaches
    # default skills to preset agents by name at activation time, so
    # skills need to already exist for a truly fresh install's
    # auto-seeded stack to actually get them, not just later ones.
    _ensure_default_skills_seeded()

    if not _GLOBAL_SEEDED_MARKER.exists():
        if not agents_store.list_agents():
            presets.activate_preset("generalist", agents_dir=agents_store.AGENTS_DIR)
            _sync_all_agent_formats(agents_store.AGENTS_DIR)
        _GLOBAL_SEEDED_MARKER.write_text("seeded\n")

    _ensure_existing_preset_agents_get_default_skills()


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


def _sync_agent_formats(agents_dir: Path, filename: str) -> None:
    """Best-effort -- a bug in the newer Codex/Gemini/Kimi translation
    must never block the primary Claude-format save, which is the one
    thing that has to always work."""
    try:
        agent = agents_store.read_agent(filename, agents_dir=agents_dir)
        other_names = {a.name for a in agents_store.list_agents(agents_dir=agents_dir) if a.filename != filename}
        agent_formats.sync_agent(agents_dir, agent, other_names)
    except Exception as exc:
        print(f"agent_formats sync failed for {filename}: {exc}")


def _sync_all_agent_formats(agents_dir: Path) -> None:
    try:
        agent_formats.sync_all(agents_dir)
    except Exception as exc:
        print(f"agent_formats sync-all failed: {exc}")


def _remove_agent_formats(agents_dir: Path, filename: str) -> None:
    try:
        agent_formats.remove_agent(agents_dir, Path(filename).stem)
    except Exception as exc:
        print(f"agent_formats remove failed for {filename}: {exc}")


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
        claude_models=providers.get("claude").models,
        gemini_models=providers.get("gemini").models,
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
    for key in ["model", "gemini_model", "effort", "color"]:
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
    _sync_agent_formats(agents_dir, filename)
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
    agents_dir = _stack_agents_dir(stack)
    agents_store.delete_agent(filename, agents_dir=agents_dir)
    _remove_agent_formats(agents_dir, filename)
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


# ---- Integrations ----


@app.get("/integrations")
@require_auth
def integrations_page():
    return render_template("integrations.html", integrations=integrations_store.list_integrations())


@app.get("/integrations/new")
@require_auth
def new_integration_form():
    return render_template("integration_form.html", integration=None)


@app.post("/integrations/new")
@require_auth
def create_integration():
    name = request.form.get("name", "").strip()
    env_var = request.form.get("env_var", "").strip()
    value = request.form.get("value", "").strip()
    if not name or not env_var or not value:
        flash("Name, environment variable, and value are all required.", "error")
        return redirect(url_for("new_integration_form"))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_var):
        flash("Environment variable must look like SLACK_BOT_TOKEN -- letters, numbers, underscores, not starting with a number.", "error")
        return redirect(url_for("new_integration_form"))
    integrations_store.add(name, env_var, value)
    flash(f"Created integration '{name}'.", "success")
    return redirect(url_for("integrations_page"))


@app.get("/integrations/<integration_id>/edit")
@require_auth
def edit_integration_form(integration_id):
    integration = integrations_store.get(integration_id)
    if integration is None:
        flash("Unknown integration.", "error")
        return redirect(url_for("integrations_page"))
    return render_template("integration_form.html", integration=integration)


@app.post("/integrations/<integration_id>/edit")
@require_auth
def edit_integration(integration_id):
    integration = integrations_store.get(integration_id)
    if integration is None:
        flash("Unknown integration.", "error")
        return redirect(url_for("integrations_page"))
    name = request.form.get("name", "").strip()
    env_var = request.form.get("env_var", "").strip()
    value = request.form.get("value", "").strip()
    if not name or not env_var:
        flash("Name and environment variable are both required.", "error")
        return redirect(url_for("edit_integration_form", integration_id=integration_id))
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_var):
        flash("Environment variable must look like SLACK_BOT_TOKEN -- letters, numbers, underscores, not starting with a number.", "error")
        return redirect(url_for("edit_integration_form", integration_id=integration_id))
    integrations_store.update(integration_id, name=name, env_var=env_var, value=value or None)
    flash(f"Saved '{name}'.", "success")
    return redirect(url_for("integrations_page"))


@app.post("/integrations/<integration_id>/delete")
@require_auth
def delete_integration(integration_id):
    integration = integrations_store.get(integration_id)
    if integration is None:
        flash("Unknown integration.", "error")
        return redirect(url_for("integrations_page"))
    integrations_store.remove(integration_id)
    flash(f"Deleted integration '{integration['name']}'.", "success")
    return redirect(url_for("integrations_page"))


# ---- Agent stack presets ----


def _activate_selection(agents_dir) -> list[str]:
    """Shared by create/edit: activates whichever preset or library
    checkboxes were submitted into agents_dir. Returns filenames written."""
    preset_id = request.form.get("preset_id", "").strip()
    agent_ids = request.form.getlist("agent_ids")
    written: list[str] = []
    if preset_id:
        written = presets.activate_preset(preset_id, agents_dir=agents_dir)
    elif agent_ids:
        written = presets.activate(agent_ids, agents_dir=agents_dir)
    if written:
        _sync_all_agent_formats(agents_dir)
    return written


def _known_directories() -> list[str]:
    """Every directory Cadre already knows about -- existing sessions'
    workdirs and existing stacks' workdirs -- so pointing a new stack at
    an already-existing project doesn't mean typing/copying its path from
    memory. Purely a convenience list; any absolute path still works."""
    dirs = {s["workdir"] for s in sessions_store.list_sessions() if not s.get("internal")}
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
        integrations=integrations_store.list_integrations(),
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

    stacks_store.update(stack_id, name=name, workdir=str(path), integration_ids=request.form.getlist("integration_ids"))

    if written:
        matching_session = next(
            (s for s in sessions_store.list_sessions() if s["workdir"] == str(path) and not s.get("internal")), None,
        )
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


def _next_schedule_fire(cron_expr: str) -> float | None:
    """Same computation session_daemon.py's scheduler loop uses to decide
    what's due -- duplicated here (rather than imported) since app.py and
    session_daemon.py are deliberately separate processes and this is a
    small, pure, side-effect-free calculation not worth coupling them
    over. Only used for the list page's "next run" display; the daemon's
    own copy is what actually decides when to fire."""
    try:
        return croniter.croniter(cron_expr, datetime.now()).get_next(datetime).timestamp()
    except (ValueError, KeyError):
        return None


def _stack_picker_options() -> list[dict]:
    """Every stack a workflow could target, global included -- the global
    team has no fixed project directory of its own, but _run_workflow
    (session_daemon.py) knows to spawn its sessions in the user's home
    directory, where only the global ~/.claude/agents team applies."""
    return [_resolve_stack(_GLOBAL_STACK_ID)] + stacks_store.list_stacks()


@app.get("/workflows")
@require_auth
def workflows_page():
    stacks_by_id = {s["id"]: s for s in _stack_picker_options()}
    workflows = workflows_store.list_workflows()
    next_run_by_id = {
        w["id"]: _next_schedule_fire(w["schedule"])
        for w in workflows
        if w.get("enabled") and w.get("trigger_type") == "schedule" and w.get("schedule")
    }
    return render_template(
        "workflows.html",
        workflows=workflows,
        stacks_by_id=stacks_by_id,
        next_run_by_id=next_run_by_id,
    )


@app.get("/workflows/new")
@require_auth
def new_workflow_form():
    return render_template(
        "workflow_form.html",
        workflow=None,
        stacks=_stack_picker_options(),
        cli_providers=providers.list_providers(),
        default_provider=settings.get("default_provider"),
    )


@app.post("/workflows/new")
@require_auth
def create_workflow():
    name = request.form.get("name", "").strip()
    stack_id = request.form.get("stack_id", "").strip()
    prompt = request.form.get("prompt", "").strip()
    provider_id = request.form.get("provider", "claude")
    if not name or not stack_id or not prompt:
        flash("Name, stack, and prompt are all required.", "error")
        return redirect(url_for("new_workflow_form"))
    if _resolve_stack(stack_id) is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("new_workflow_form"))

    trigger_type = request.form.get("trigger_type", "manual")
    schedule = _workflow_schedule_from_form() if trigger_type == "schedule" else None
    session_mode = request.form.get("session_mode", "fresh")
    # Unattended is only ever honored for Claude (see providers.py's
    # _add_unattended) -- refusing to even record it as on for another
    # provider avoids a workflow silently believing it's unattended when
    # it never actually will be.
    unattended = request.form.get("unattended") == "on" and provider_id == "claude"

    workflows_store.add(
        name, stack_id, prompt, provider_id,
        trigger_type=trigger_type, schedule=schedule,
        session_mode=session_mode, unattended=unattended,
    )
    flash(f"Created workflow '{name}'.", "success")
    return redirect(url_for("workflows_page"))


@app.get("/workflows/<workflow_id>/edit")
@require_auth
def edit_workflow_form(workflow_id):
    workflow = workflows_store.get(workflow_id)
    if workflow is None:
        flash("Unknown workflow.", "error")
        return redirect(url_for("workflows_page"))
    return render_template(
        "workflow_form.html",
        workflow=workflow,
        stacks=_stack_picker_options(),
        cli_providers=providers.list_providers(),
        default_provider=settings.get("default_provider"),
    )


@app.post("/workflows/<workflow_id>/edit")
@require_auth
def edit_workflow(workflow_id):
    workflow = workflows_store.get(workflow_id)
    if workflow is None:
        flash("Unknown workflow.", "error")
        return redirect(url_for("workflows_page"))

    name = request.form.get("name", "").strip()
    stack_id = request.form.get("stack_id", "").strip()
    prompt = request.form.get("prompt", "").strip()
    provider_id = request.form.get("provider", "claude")
    if not name or not stack_id or not prompt:
        flash("Name, stack, and prompt are all required.", "error")
        return redirect(url_for("edit_workflow_form", workflow_id=workflow_id))
    if _resolve_stack(stack_id) is None:
        flash("Unknown stack.", "error")
        return redirect(url_for("edit_workflow_form", workflow_id=workflow_id))

    trigger_type = request.form.get("trigger_type", "manual")
    schedule = _workflow_schedule_from_form() if trigger_type == "schedule" else None
    session_mode = request.form.get("session_mode", "fresh")
    unattended = request.form.get("unattended") == "on" and provider_id == "claude"
    # Switching a "reuse" workflow to a different stack/provider, or back
    # to "fresh", invalidates whatever session was previously pinned --
    # the next run should start a new one rather than resuming a session
    # that may no longer make sense for the new config.
    if session_mode != "reuse" or stack_id != workflow["stack_id"] or provider_id != workflow["provider"]:
        workflows_store.clear_pinned_session(workflow_id)

    workflows_store.update(
        workflow_id, name=name, stack_id=stack_id, prompt=prompt, provider=provider_id,
        trigger_type=trigger_type, schedule=schedule, session_mode=session_mode, unattended=unattended,
    )
    flash(f"Saved '{name}'.", "success")
    return redirect(url_for("workflows_page"))


@app.post("/workflows/<workflow_id>/delete")
@require_auth
def delete_workflow(workflow_id):
    workflow = workflows_store.get(workflow_id)
    if workflow is None:
        flash("Unknown workflow.", "error")
        return redirect(url_for("workflows_page"))
    workflows_store.remove(workflow_id)
    flash(f"Deleted workflow '{workflow['name']}'.", "success")
    return redirect(url_for("workflows_page"))


@app.post("/workflows/<workflow_id>/run")
@require_auth
def run_workflow_now(workflow_id):
    workflow = workflows_store.get(workflow_id)
    if workflow is None:
        flash("Unknown workflow.", "error")
        return redirect(url_for("workflows_page"))
    session_manager.run_workflow(workflow_id)
    flash(f"Running '{workflow['name']}' -- check back shortly for its status.", "success")
    return redirect(url_for("workflows_page"))


def _workflow_schedule_from_form() -> str | None:
    """Builds a cron expression from the form's schedule fields -- either
    a friendly preset (hourly/daily-at-time/every-N-minutes) or, if
    "advanced" was chosen, whatever raw cron string was typed directly.
    Phase 1 only stores this string; nothing acts on it until the
    scheduler (phase 2) exists."""
    preset = request.form.get("schedule_preset", "daily")
    if preset == "advanced":
        return request.form.get("schedule_cron", "").strip() or None
    if preset == "hourly":
        return "0 * * * *"
    if preset == "every_n_minutes":
        n = request.form.get("schedule_minutes", "").strip()
        n = n if n.isdigit() and int(n) > 0 else "15"
        return f"*/{n} * * * *"
    # "daily" (default): a specific hour:minute, 24h fields from the form
    hour = request.form.get("schedule_hour", "").strip()
    minute = request.form.get("schedule_minute", "").strip()
    hour = hour if hour.isdigit() and 0 <= int(hour) <= 23 else "9"
    minute = minute if minute.isdigit() and 0 <= int(minute) <= 59 else "0"
    return f"{minute} {hour} * * *"




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
    _sync_agent_formats(agents_dir, filename)
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
    # Home directory, not settings.projects_root() -- confirmed via live
    # testing 2026-08-10 that defaulting to the configured projects root
    # backfires the moment it doesn't exist yet: projects_root() creates
    # it on the spot (mkdir(parents=True, exist_ok=True)), so the browser
    # opens straight into a brand-new, genuinely empty folder with no
    # obvious explanation why nothing's there. Home has real, familiar
    # content to navigate from regardless of whether projects_root has
    # ever been used -- the text fields' own placeholder/autocomplete
    # still point at projects_root as the *suggested* new path, this only
    # changes where clicking "Browse" with an empty field starts looking.
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
        default_base=str(settings.projects_root()),
        known_dirs=_known_directories(),
        stacks=_stack_picker_options(),
    )


@app.post("/sessions/new")
@require_auth
def create_session():
    label = request.form.get("label", "").strip()
    source = request.form.get("source", "local")

    if source in ("github", "gitlab"):
        token = git_hosts.get_token(source)
        if not token:
            flash(f"Connect your {source.title()} account first.", "error")
            return redirect(url_for("new_session_form"))

        new_repo_name = request.form.get("new_repo_name", "").strip()
        if new_repo_name:
            create_repo = git_hosts.github_create_repo if source == "github" else git_hosts.gitlab_create_repo
            private = request.form.get("new_repo_private") == "on"
            try:
                clone_url = create_repo(token, new_repo_name, private=private)
            except Exception as exc:
                flash(f"Couldn't create that repo on {source.title()}: {exc}", "error")
                return redirect(url_for("new_session_form"))
            repo_full_name = new_repo_name
        else:
            repo_full_name = request.form.get("repo_full_name", "").strip()
            if not repo_full_name:
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
        # Cadre's own clone above only authenticates itself, one-off --
        # this persists the same credentials into the repo's own config so
        # `git push`/`git pull` run later by the agent inside the session
        # (not just this clone) stay authenticated as the connected
        # account, and so reconnecting later (relink_all, in set_token)
        # re-applies automatically without re-cloning.
        try:
            git_hosts.link_workdir(workdir, source)
        except Exception as exc:
            print(f"git_hosts.link_workdir failed for {workdir}: {exc}")
    else:
        stack_id = request.form.get("stack_id", "").strip()
        stack = _resolve_stack(stack_id) if stack_id else None
        if stack:
            # Any selected stack -- real (has its own workdir) or Global
            # (doesn't, falls back to projects_root as the base) --
            # auto-creates a folder named after the label. No path typed
            # or browsed either way. Confirmed via real feedback
            # 2026-08-10 that Global falling through to "no, type a path
            # yourself" here (the previous stack.get("workdir") check
            # excluded it) was wrong -- Global not having one *fixed*
            # directory doesn't mean it needs a human to type one by
            # hand every time, same as a real stack doesn't.
            if not label:
                flash("Label is required.", "error")
                return redirect(url_for("new_session_form"))
            base = Path(stack["workdir"]) if stack.get("workdir") else settings.projects_root()
            slug = git_hosts.slugify_repo_name(label)
            target_dir = base / slug
            suffix = 2
            while target_dir.exists():
                target_dir = base / f"{slug}-{suffix}"
                suffix += 1
            target_dir.mkdir(parents=True, exist_ok=True)
            workdir = str(target_dir)
        else:
            workdir = request.form.get("workdir", "").strip()
            if not label or not workdir:
                flash("Label and working directory are both required.", "error")
                return redirect(url_for("new_session_form"))
            if not Path(workdir).is_dir():
                flash(f"'{workdir}' is not a directory that exists on this machine.", "error")
                return redirect(url_for("new_session_form"))
            # Not a repo Cadre itself cloned -- but if it's an existing
            # git checkout of a repo on a connected GitHub/GitLab account,
            # link it the same way so push/pull work here too, same as a
            # freshly-cloned one. Harmless no-op for a plain folder or a
            # repo on an unconnected/different host (detect_git_host
            # returns None).
            try:
                detected = git_hosts.detect_git_host(workdir)
                if detected and git_hosts.get_token(detected):
                    git_hosts.link_workdir(workdir, detected)
            except Exception as exc:
                print(f"git_hosts existing-repo link check failed for {workdir}: {exc}")

    provider_id = request.form.get("provider", "claude") if source == "local" else "claude"
    try:
        terminal_theme.apply_theme(workdir, provider_id, settings.get("terminal_theme"))
    except Exception as exc:
        print(f"terminal_theme apply failed for {workdir}: {exc}")
    # autostart=False -- deliberately NOT spawning the pty here. Doing so
    # would use session_daemon.py's generic wide-desktop size guess, and a
    # freshly-spawned CLI whose live status/recap redraw assumed that
    # width can render corrupted once the terminal hub (below) opens with
    # the browser's real, usually-narrower size and forces a resize.
    # Landing on the terminal hub with ?autostart=1 instead makes it spawn
    # the pty itself, the same way Restart already correctly does from an
    # open terminal view -- with real cols/rows from the start, no resize
    # needed. See create()'s autostart docstring for the full diagnosis.
    result = session_manager.create(label, workdir, provider=provider_id, autostart=False)
    flash(f"Created session '{label}'.", "success")
    return redirect(url_for("terminal_hub", session=result["session_id"], autostart=1))


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
    # Sweeps only genuinely stale (see _CONNECTOR_SESSION_STALE_SECONDS)
    # leftover internal connector sessions -- a backstop for a truly
    # abandoned flow, not an aggressive every-page-load teardown (that
    # was a real bug: it could kill a session still actively in use just
    # from navigating back to this page -- see
    # _discard_internal_connector_sessions' docstring).
    _discard_internal_connector_sessions(min_age_seconds=_CONNECTOR_SESSION_STALE_SECONDS)
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
        current_username=auth.get_username(),
        has_security_question=auth.has_security_question(),
        current_host=config.HOST,
        tailscale=network_info.tailscale_status(),
        connector_status=providers.claude_mcp_connectors(),
    )


_CONNECTOR_SESSION_LABEL = "Cadre: Connectors"


_CONNECTOR_SESSION_STALE_SECONDS = 600  # 10 minutes


def _discard_internal_connector_sessions(min_age_seconds: float = 0) -> None:
    """Tears down leftover internal connector sessions older than
    min_age_seconds. Two very different call sites use this:

    - Explicitly clicking "Connect" passes 0 (discard unconditionally) --
      that's a deliberate "start fresh" action, so whatever session
      existed before genuinely should go.
    - Settings' own page load passes _CONNECTOR_SESSION_STALE_SECONDS,
      as a backstop for a truly abandoned flow (browser closed mid-setup,
      etc.). Confirmed via real user testing 2026-08-10 that discarding
      unconditionally here was a real bug: simply navigating back to
      Settings (or clicking Connect a second time) while a connector
      session's terminal tab was still open elsewhere silently killed it
      out from under that tab, which then showed "unknown session" --
      the age gate keeps the self-cleaning behavior for genuinely
      abandoned sessions without nuking one still actively in use."""
    now = time.time()
    for s in sessions_store.list_sessions():
        if s.get("internal") and s["label"] == _CONNECTOR_SESSION_LABEL:
            if now - s.get("created_at", 0) >= min_age_seconds:
                session_manager.stop(s["id"])
                sessions_store.remove(s["id"])


def _create_connector_session() -> str:
    """A fresh, internal (hidden from the normal session list -- see
    sessions_store.add's internal flag) session for driving Claude Code's
    own /mcp picker. Not reused across connects and torn down again once
    the user's done (see _discard_internal_connector_sessions) -- this
    exists purely as a vehicle for that one menu, not something anyone
    should find or manage as an ordinary session. Claude only: no
    equivalent of /mcp exists on the other providers."""
    _discard_internal_connector_sessions()
    result = session_manager.create(_CONNECTOR_SESSION_LABEL, str(Path.home()), provider="claude", internal=True)
    return result["session_id"]


@app.post("/settings/connectors/<name>/connect")
@require_auth
def connect_mcp_connector(name):
    if name not in providers.CLAUDE_CONNECTOR_LABELS:
        return {"ok": False, "error": "unknown connector"}
    session_id = _create_connector_session()
    result = session_manager.start_mcp_connector_session(session_id)
    result["session_id"] = session_id
    return result


@app.get("/settings/connectors/result")
@require_auth
def poll_mcp_connector_result():
    session_id = request.args.get("session_id", "").strip()
    if not session_id:
        return {"ok": False, "error": "missing session_id"}
    data = session_manager.get_mcp_connector_session_result(session_id)
    if not data.get("pending") and data.get("result", {}).get("ok"):
        data["terminal_url"] = url_for("session_terminal", session_id=session_id)
    return data


@app.post("/settings/connectors/status")
@require_auth
def refresh_mcp_connector_status():
    _discard_internal_connector_sessions()
    return {"ok": True, "connector_status": providers.claude_mcp_connectors()}


@app.get("/settings/git-hosts/<provider>/verify")
@require_auth
def verify_git_host(provider):
    # A stored token only proves *something* was saved once -- not that
    # the account is still actually reachable with it (revoked access,
    # an expired/rotated secret, or -- the concrete case that prompted
    # this -- an OAuth authorize attempt that never actually completed
    # because the callback URL registered on GitHub/GitLab's side didn't
    # exactly match the one Cadre sent, so no token ever landed at all).
    # Hits the real API so Settings can show what's actually true instead
    # of what's merely on disk.
    if provider not in ("github", "gitlab"):
        return {"ok": False, "error": "unknown provider"}, 404
    token = git_hosts.get_token(provider)
    if not token:
        return {"ok": True, "connected": False}
    verify = git_hosts.github_verify_token if provider == "github" else git_hosts.gitlab_verify_token
    result = verify(token)
    if result is None:
        return {"ok": True, "connected": False, "token_present": True}
    return {"ok": True, "connected": True, "login": result.get("login")}


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


_SETTINGS_TABS = {"account", "version", "githosts", "providers", "sessions", "appearance"}


def _apply_terminal_theme_to_all_sessions(choice: str) -> int:
    """Rewrites every known session's own provider config to the given
    theme (dark/light/auto) -- apply_theme() otherwise only ever runs at
    session-creation time, so without this, changing the theme would
    affect new sessions only. A CLI that's already running read its
    config at startup, though, so this alone won't change what's on
    screen for a running session -- it still needs a restart (via its
    own Start/Stop/Restart controls) to re-read the file just written."""
    applied = 0
    for entry in sessions_store.list_sessions():
        try:
            terminal_theme.apply_theme(entry["workdir"], entry.get("provider", "claude"), choice)
            applied += 1
        except Exception as exc:
            print(f"terminal_theme re-apply failed for {entry.get('workdir')}: {exc}")
    return applied


@app.post("/settings/terminal-theme")
@require_auth
def save_terminal_theme():
    # Lives on the terminal pages themselves, not in Settings -- it's
    # about the CLI running inside a session, which is right where you're
    # looking at it, not a dashboard-wide preference buried in a form.
    choice = request.form.get("terminal_theme", "")
    if choice not in dict(TERMINAL_THEME_OPTIONS):
        return {"ok": False, "error": "invalid theme"}, 400
    settings.update(terminal_theme=choice)
    applied = _apply_terminal_theme_to_all_sessions(choice)
    return {"ok": True, "applied": applied}


@app.post("/settings")
@require_auth
def save_settings():
    active_tab = request.form.get("active_tab", "")
    anchor = active_tab if active_tab in _SETTINGS_TABS else None

    fields = {
        "github_client_id": request.form.get("github_client_id", ""),
        "gitlab_base_url": request.form.get("gitlab_base_url", "").rstrip("/") or "https://gitlab.com",
        "gitlab_client_id": request.form.get("gitlab_client_id", ""),
        "projects_root": request.form.get("projects_root", ""),
    }
    dashboard_theme_choice = request.form.get("dashboard_theme", "")
    if dashboard_theme_choice in DASHBOARD_THEME_VALUES:
        fields["dashboard_theme"] = dashboard_theme_choice
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
            return redirect(url_for("settings_form", _anchor=anchor))
        fields["default_provider"] = default_provider

    settings.update(**fields)
    flash("Settings saved.", "success")
    return redirect(url_for("settings_form", _anchor=anchor))


@app.post("/settings/account")
@require_auth
def save_account():
    current_password = request.form.get("current_password", "")
    new_username = request.form.get("new_username", "").strip()
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    new_security_question = request.form.get("new_security_question", "").strip()
    new_security_answer = request.form.get("new_security_answer", "").strip()

    if not current_password:
        flash("Current password is required to change any account settings.", "error")
        return redirect(url_for("settings_form", _anchor="account"))
    if new_password and new_password != confirm_password:
        flash("New password and confirmation didn't match.", "error")
        return redirect(url_for("settings_form", _anchor="account"))
    if new_password and len(new_password) < 8:
        flash("New password should be at least 8 characters.", "error")
        return redirect(url_for("settings_form", _anchor="account"))
    if bool(new_security_question) != bool(new_security_answer):
        flash("Set both a new security question and an answer, not just one.", "error")
        return redirect(url_for("settings_form", _anchor="account"))
    if not any((new_username, new_password, new_security_question)):
        flash("Nothing to change.", "error")
        return redirect(url_for("settings_form", _anchor="account"))

    ok, error = auth.change_credentials(
        current_password,
        new_username=new_username or None,
        new_password=new_password or None,
        new_security_question=new_security_question or None,
        new_security_answer=new_security_answer or None,
    )
    if not ok:
        flash(error, "error")
        return redirect(url_for("settings_form", _anchor="account"))

    if new_username:
        session["user"] = new_username
    flash("Account updated.", "success")
    return redirect(url_for("settings_form", _anchor="account"))


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


def _sessions_grouped_by_stack() -> list[dict]:
    """Each session's only link to a stack is its workdir -- there's no
    stack_id field on a session record, so this matches the same way
    session_detail() already does (exact workdir string match). Anything
    that doesn't match a real stack's own directory falls under the
    synthetic Global stack, same fallback semantics as everywhere else
    a session's stack is resolved."""
    stacks = _stacks_with_agent_counts()
    sessions = _sessions_with_status()
    groups = [{"stack": stack, "sessions": []} for stack in stacks]
    global_group = next(g for g in groups if g["stack"].get("is_global"))
    for session in sessions:
        matched = next((g for g in groups if g["stack"].get("workdir") == session["workdir"]), None)
        (matched or global_group)["sessions"].append(session)
    return groups


@app.get("/terminal")
@require_auth
def terminal_hub():
    """Nav-level Terminal page -- a session sidebar plus whichever one's
    active, distinct from the single-session focused view at
    /sessions/<id>/terminal. Which session is "active" is resolved
    client-side (query param, else localStorage's last-used session),
    so this route just needs to hand over the session list, grouped by
    whichever Agent Stack (if any) controls each one's directory."""
    return render_template("terminal_hub.html", stack_groups=_sessions_grouped_by_stack())


@app.get("/sessions/<session_id>/terminal")
@require_auth
def session_terminal(session_id):
    """A dedicated, chrome-free terminal page -- bookmarkable, and works
    as an "Add to Home Screen" target on mobile so opening a session
    feels like tapping into an app rather than digging through the
    dashboard each time."""
    entry = sessions_store.get(session_id)
    if entry is None:
        flash("Unknown session.", "error")
        return redirect(url_for("index"))
    return render_template("session_terminal.html", session=entry)


@app.post("/sessions/<session_id>/handoff")
@require_auth
def session_handoff(session_id):
    """Retires a bloated/long-running session by creating a fresh one in
    the same directory (same provider) and stopping the old one -- for
    this to actually save tokens rather than just moving the same
    problem, the new session needs to actually pick up where the old one
    left off, which is what ensure_continuity_nudge is for: it's the
    thing that makes a fresh session go read PROJECT_STATUS.md instead
    of re-deriving context from scratch."""
    entry = sessions_store.get(session_id)
    if entry is None:
        flash("Unknown session.", "error")
        return redirect(url_for("index"))

    presets.ensure_continuity_nudge(Path(entry["workdir"]))

    result = session_manager.create(f"{entry['label']} (new)", entry["workdir"], provider=entry.get("provider", "claude"))
    session_manager.stop(session_id)
    flash(f"Handed off to a new session (pid {result.get('pid')}) — the old one is stopped, not deleted.", "success")
    return redirect(url_for("session_detail", session_id=result["session_id"]))


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
    # Optional -- only ever sent by a start/restart triggered from an
    # already-open terminal view (it already knows its own real size at
    # that point), not by the plain sessions list. Threaded straight
    # through to the pty's initial size instead of the daemon's generic
    # guess, so a --resume'd session's startup recap renders at the
    # width it's actually about to be viewed at instead of baking a
    # possibly-wrong width into its backlog forever.
    cols = request.form.get("cols", type=int)
    rows = request.form.get("rows", type=int)
    if action == "start":
        session_manager.start(session_id, cols=cols, rows=rows)
    elif action == "stop":
        session_manager.stop(session_id)
    elif action == "restart":
        session_manager.restart(session_id, cols=cols, rows=rows)
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
