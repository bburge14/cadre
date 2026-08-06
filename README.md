# Cadre

A self-hosted, single-user web app for running and managing AI coding
sessions — Claude, Gemini, Codex, or Kimi, your choice per session — plus
**Agent Stacks**: a directory-scoped subagent team (Claude Code's own
native `.claude/agents/` mechanism) for any project, not just one global
team. A shared **Skills** library lets any agent in any stack pull in the
same reusable instructions. See `SETUP.md` to install your own copy.

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
  see "AI CLI providers" in `SETUP.md`. Small colored badges (not real
  brand logos — this app fetches no external assets) show which provider
  each agent actually uses, in a stack's agent table and its diagram.
- **Setup wizard & default AI**: `/wizard` (shown once right after
  creating your admin account, or reachable anytime from Settings) walks
  through picking a provider, connecting it, and setting it as your
  default — pre-fills new sessions and is meant to be the one that runs
  your Agent Stacks. The default picker only ever offers a provider that's
  both actually connected *and* capable of running a stack — today that's
  Claude only, since Agent Stacks is Claude Code's own native subagent
  mechanism and no other CLI's binary reads `.claude/agents/` (yet — see
  "What's next" below).
- **Multi-stack**: more than one agent team can exist at once, each tied to
  a directory via Claude Code's native per-project `.claude/agents/`
  override (`/stacks/<id>/edit` — create/edit/delete named stacks). The
  global team at `~/.claude/agents/` that still applies wherever a more
  specific stack doesn't isn't a separate system -- it's a synthetic
  `stack_id="global"` entry (`_resolve_stack()` in `app.py`) using the
  exact same routes/templates as any real stack, just without a directory
  to rename or delete.
- **Interactive terminal**: every session's detail page can open a real
  xterm.js terminal over a token-authed WebSocket into that session's pty,
  not just a read-only output feed — the only way to interact with
  Gemini/Codex/Kimi sessions today, since none of them has an official
  remote-control equivalent yet.
- **Skills**: one shared list (`/skills`, `~/.claude/skills/`, unlike
  agents there's no per-stack scoping) usable by every agent in every
  stack, managed via `skills_store.py`. A skill is a different mechanism
  from an agent -- packaged instructions loaded into whatever session
  invokes it, not a separate spawned worker -- one directory per skill
  (`<name>/SKILL.md`), just name/description frontmatter and a body.
  Attaching a skill to a specific agent happens on that agent's own edit
  page (a searchable checklist), which rewrites the agent's system prompt
  with an auto-generated block naming the selected skills -- not a native
  per-agent field, since nothing confirms Claude Code has one.
- **Trust-prompt handling**: a brand-new session in a directory Claude
  hasn't seen before blocks on an interactive "trust this folder?" prompt.
  `session_daemon.py`'s reader thread watches for that specific prompt
  (after stripping ANSI/cursor-position codes) and answers "yes" — it never
  sends that keystroke blindly, only after actually seeing the prompt text.
  The same reader also watches for usage/rate-limit messages and flags them
  on the dashboard — see "AI CLI providers" in `SETUP.md`.
- **Directory browser**: every path field (a stack's directory, a
  session's working directory, Settings' projects root) has a "Browse…"
  button that lists real subdirectories on this machine (`GET
  /api/browse-dirs`) and fills the field for you — a browser's native
  file picker can't hand a page a real filesystem path, so this walks the
  filesystem server-side instead, on the same machine those paths refer
  to.
- **Contextual help**: a small "?" next to anything unconfigured or
  non-obvious (a CLI not found on `PATH`, an agent's primary provider not
  actually connected, the agent/skill creation forms) expands inline
  install commands, docs links, or pointers instead of leaving a bare
  warning.
- **External adoption**: status/start/stop all match by session UUID via
  `psutil`-based process discovery, so a session started outside this app
  (desktop icon, manual `claude --resume ... --remote-control`) is
  detected and managed rather than duplicated.
- **Updating**: Settings shows the running version (`VERSION`), checks
  GitHub's releases API for a newer one, and can apply it in-place with an
  "Update now" button — `git pull` for a git-clone install, or downloads
  and merges in the latest release ZIP for a ZIP-downloaded one (`venv/`,
  `instance/`, `.env` are never touched, since none of those exist in a
  release ZIP) — then reinstalls deps and auto-restarts the dashboard once
  it's back. Never touches the session daemon. A git-clone-only terminal
  equivalent is also available via `linux/update.sh` / `macos/update.sh` /
  `windows\update.bat` — see "Updating" in `SETUP.md`.

## What's next: non-Claude Agent Stacks

Right now Agent Stacks only run in Claude sessions — that's the current
state, not a permanent one. Codex CLI, Gemini CLI, and Kimi Code CLI have
each since shipped their own native subagent-delegation mechanism
(config-file-driven, conceptually the same idea as Claude Code's
`.claude/agents/*.md` + Task tool, just three different formats: TOML for
Codex, Markdown+YAML for Gemini and Kimi) and confirmed genuine multi-step
agentic behavior in their non-interactive modes — so a from-scratch
orchestration engine isn't needed to get there. What's missing is a
translation layer: the same agent definitions this app already manages,
compiled to whichever format matches a given stack's target provider and
written to that provider's own config directory. Not yet built.

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
