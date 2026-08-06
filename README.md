# Cadre

A self-hosted, single-user web app for managing multiple Claude Code
sessions (each reachable remotely via claude.ai/code) and the global agent
team at `~/.claude/agents/` that all of them share. See `SETUP.md` to
install your own copy.

Runs well as a systemd `--user` service (`cadre-app.service`),
enabled + lingering, so it's always up — no manual start needed. See
`SETUP.md` for the unit file.

- **URL**: `http://127.0.0.1:7420` by default; widen to your network via
  `COMMAND_CENTER_HOST=0.0.0.0` in `.env` (see `SETUP.md`)
- **Auth**: real account (username + hashed password), created via a
  one-time `/setup` wizard on first run, session-cookie login, CSRF
  protection on every state-changing request
- **Session registry**: `instance/sessions.json` — id (a real Claude Code
  session UUID), label, working directory
- **Process model**: each session runs under a real pty (not headless —
  `claude`'s remote-control needs a TTY, and the other providers' CLIs are
  interactive too). Ownership of every pty lives in a separate
  `session_daemon.py` process (talked to over a TCP loopback socket,
  `127.0.0.1` only — not a Unix domain socket, so the exact same code runs
  on Windows), not in `app.py` itself — see "Two processes, on purpose" in
  `SETUP.md`. This is what makes sessions survive the web app being
  redeployed/restarted/crashing; only a restart of the daemon itself
  (rare) still ends them.
- **Multi-provider**: a session can run Claude, Gemini, Codex, or Kimi
  (`providers.py`). Claude uses its own account login via the CLI itself;
  the other three are API-key only (Settings). Any agent can also
  "delegate" its actual work to one of these via an auto-generated
  instruction block, regardless of which provider its own session runs —
  see "AI CLI providers" in `SETUP.md`.
- **Multi-stack**: more than one agent team can exist at once, each tied to
  a directory via Claude Code's native per-project `.claude/agents/`
  override (`/stacks` — create/edit/delete named stacks). One global team
  at `~/.claude/agents/` still applies wherever a more specific stack
  doesn't.
- **Interactive terminal**: every session's detail page can open a real
  xterm.js terminal over a token-authed WebSocket into that session's pty,
  not just a read-only output feed — the only way to interact with
  Gemini/Codex/Kimi sessions today, since none of them has an official
  remote-control equivalent yet.
- **Trust-prompt handling**: a brand-new session in a directory Claude
  hasn't seen before blocks on an interactive "trust this folder?" prompt.
  `session_daemon.py`'s reader thread watches for that specific prompt
  (after stripping ANSI/cursor-position codes) and answers "yes" — it never
  sends that keystroke blindly, only after actually seeing the prompt text.
  The same reader also watches for usage/rate-limit messages and flags them
  on the dashboard — see "AI CLI providers" in `SETUP.md`.
- **External adoption**: status/start/stop all match by session UUID via
  `psutil`-based process discovery, so a session started outside this app
  (desktop icon, manual `claude --resume ... --remote-control`) is
  detected and managed rather than duplicated.
- **Updating**: Settings shows the running version (`VERSION`) and can
  check GitHub's releases API for a newer one — check-only, never applies
  anything itself. `linux/update.sh` / `macos/update.sh` /
  `windows\update.bat` actually pull and apply one (`git pull` + reinstall
  deps), restarting only the dashboard, never the session daemon — see
  "Updating" in `SETUP.md`.

## Operational notes

- Editing/creating/deleting an agent `.md` file restarts every currently
  *running* session automatically, so the new team definition takes effect
  without you having to remember to do it.
- Deleting a session normally just stops it and removes it from the list;
  checking "also permanently delete conversation history" on top of that
  additionally deletes the underlying `~/.claude/projects/*/<uuid>.jsonl`
  transcript — irreversible.
- A desktop launcher or any other script that runs
  `claude --resume <uuid> --remote-control` directly can coexist with this
  app managing the same session without conflict, thanks to the UUID-based
  external-process detection above.
