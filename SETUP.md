# Brad's Agent Stack Creator — Setup

A web dashboard for managing multiple Claude Code sessions (each reachable
remotely via claude.ai/code) and the global subagent team they all share.
This is self-hosted, single-user software: you run your own copy on your
own machine, under your own Claude account. There's no shared server and no
account system beyond the one admin login you create for yourself below.

## What's in git vs. what's yours alone

| In this repo (git) | Never in git — created on your machine |
|---|---|
| `app.py`, `auth.py`, `config.py`, `session_manager.py`, `sessions_store.py`, `agents_store.py` | `instance/` — your admin account, your sessions list, your signing key |
| `templates/`, `requirements.txt` | `.env` — your local config overrides |
| `.env.example`, `SETUP.md`, `.gitignore`, `LICENSE` | `venv/` — rebuild fresh per machine, never copy |

## Prerequisites

- Python 3.10+ (`python3 --version` to check)
- The `claude` CLI installed and working (`claude --version`), logged into
  your own Anthropic account (`claude`, then `/login`) on a Pro, Max, Team,
  or Enterprise plan — Remote Control isn't available on API-key-only
  setups
- On Linux, if you want this running as an always-on background service:
  `systemd --user` (already present on basically every modern distro)

## Steps (Linux / macOS)

1. **Get the code**:
   ```bash
   git clone <this-repo-url> ~/.claude/command-center
   cd ~/.claude/command-center
   ```

2. **Create the virtual environment**:
   ```bash
   python3 -m venv venv
   ./venv/bin/pip install -r requirements.txt
   ```

3. **(Optional) copy the config template** if you want to change any
   default (port, host, etc.) — otherwise skip this, every value has a
   working default:
   ```bash
   cp .env.example .env
   # edit .env as needed
   ```

4. **Run it**:
   ```bash
   ./venv/bin/python app.py
   ```
   You should see `Running on http://127.0.0.1:7420` (or whatever host/port
   you configured).

5. **Open it in a browser** at that address. First visit should redirect
   you to an account-creation page — pick a username and password (this is
   the only account this instance will ever have). After creating it,
   you're redirected to log in, and then land on an empty dashboard: "No
   sessions yet." That's success.

6. **Create your first session** via "+ New session" — give it a label and
   a working directory that already exists on this machine, e.g. a project
   you're working on. It'll launch `claude` there with Remote Control
   enabled; the session's detail page shows the connect URL/QR once it's
   up.

## Connecting GitHub / GitLab (optional)

You don't need to touch `.env` for this — go to **Settings** (top-right of
the dashboard once logged in). It shows you the exact callback URL to
register, and everything you paste in there (Client ID/Secret, GitLab base
URL, where repos get cloned to) is saved immediately, no restart required:

1. Register an OAuth App: github.com/settings/developers (GitHub) or your
   GitLab instance's User Settings → Applications (GitLab). Use the
   callback URL shown on the Settings page.
2. Paste the Client ID/Secret into Settings and save.
3. Back on "+ New session," the GitHub/GitLab tab now shows a "Connect your
   account" link — click it, authorize on their site, and you're taken back
   here. From then on, picking a repo from a dropdown clones it and starts
   a session there, same as pointing at a local directory.

Skip this section entirely if you only ever plan to point sessions at
directories already on this machine — nothing else depends on it.

## Two processes, on purpose

This app is actually two pieces:

- **`app.py`** — the web dashboard (auth, templates, agent editing). You'll
  restart/redeploy this often as you make changes.
- **`session_daemon.py`** — a separate, much simpler process that actually
  owns each Claude Code session's terminal (a pty) and keeps it alive. It
  talks to `app.py` over a local Unix socket (`instance/daemon.sock`).

They're split up deliberately: a session's aliveness depends on *something*
keeping its pty open continuously, and that something must never be the web
app you're actively iterating on — otherwise every redeploy or crash of the
dashboard kills every live session. `session_daemon.py` has no business
logic (no auth, no templates, no routes) and essentially never needs
restarting during normal use, so this isolates that risk to something rare.

If the daemon isn't running yet, `app.py` will auto-launch it the first
time it's needed — so this all works even with zero manual setup. For a
proper always-on install, though, run both as services (below).

**The one residual limitation**: if the *daemon itself* ever restarts or
crashes, any sessions it's actively holding open do die (this is fewer,
rarer restarts than the dashboard sees, but it's not zero — a `tmux`/
`screen`-based redesign could close this gap further if it ever matters).

## Running it as an always-on background service (Linux)

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/claude-session-daemon.service <<'EOF'
[Unit]
Description=Brad's Agent Stack Creator - session daemon (owns pty/process lifecycle)

[Service]
Type=simple
WorkingDirectory=%h/.claude/command-center
ExecStart=%h/.claude/command-center/venv/bin/python session_daemon.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

cat > ~/.config/systemd/user/claude-command-center.service <<'EOF'
[Unit]
Description=Brad's Agent Stack Creator
Wants=claude-session-daemon.service
After=claude-session-daemon.service

[Service]
Type=simple
WorkingDirectory=%h/.claude/command-center
ExecStart=%h/.claude/command-center/venv/bin/python app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now claude-session-daemon.service claude-command-center.service
loginctl enable-linger "$USER"   # keeps both running even when you're logged out
```

Check both came up: `systemctl --user status claude-session-daemon.service
claude-command-center.service` should show `active (running)` for each.

On macOS, there's no systemd — just run `./venv/bin/python app.py` in a
terminal you leave open, or wrap it in your own `launchd` plist if you want
it persistent.

## Reaching it from another device (Tailscale/LAN)

By default this only listens on `127.0.0.1` — reachable from this machine
alone. To reach it from your phone or another device on your Tailscale
network or LAN, set `COMMAND_CENTER_HOST=0.0.0.0` in `.env` and restart.
**Do not** additionally expose that port to the open internet without a
reverse proxy handling TLS — this is a plain-HTTP dev server underneath,
and while it now has real login/CSRF protection, it was never hardened
against being placed directly on the public internet.

## Per-machine settings to double check

- `CLAUDE_BIN` in `.env` — only needed if `claude` isn't on the `PATH` that
  this app's Python process sees (rare; matters more if you're running it
  as a service under a minimal environment).
- `CLAUDE_AGENTS_DIR` in `.env` — only needed if you want this instance to
  manage a subagent-definitions directory other than the standard
  `~/.claude/agents`.
