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

## What does this do?

Cadre is a command center for running AI coding agents across all of your
projects at once, from a browser, instead of a pile of terminal windows
you have to remember to check on.

- **Run sessions, not just one at a time.** Spin up a session per
  project — pick a directory and a provider (Claude, Gemini, Codex, or
  Kimi) — and it keeps running as a real background process, checkable
  from any device on your network, and it survives you closing the tab
  or even redeploying the dashboard itself.
- **Give each project a team, not just a chat.** An Agent Stack is a
  named group of subagents (a coder, a reviewer, a deployer — whatever
  roles you define) scoped to one project's directory, built on Claude
  Code's own native subagent mechanism. Different projects can have
  totally different teams, all managed from the same place.
- **Write instructions once, reuse them everywhere.** A shared Skills
  library lets any agent in any stack pull in the same reusable
  checklist, house style, or workflow instead of it being copy-pasted
  into a dozen different agent prompts.
- **Actually drive the CLI, not just watch it.** Every session gets a
  real interactive terminal in the browser (not a read-only log), which
  is currently the only way to remote-control Gemini/Codex/Kimi sessions
  at all, since none of them ship an official remote-control feature of
  their own the way Claude Code does.
- **Handle the busywork around all of that**, too: a one-time setup
  wizard for picking your default provider, account login with
  security-question recovery, a directory browser for path fields
  instead of typing them by hand, trust-prompt auto-confirmation, usage-
  limit detection, in-app self-updating, and a set of dashboard/terminal
  color themes to make staring at it all day less miserable.

- **URL**: `http://127.0.0.1:7420` by default; widen to your network via
  `COMMAND_CENTER_HOST=0.0.0.0` in `.env` (see `SETUP.md`)
- **Auth**: real account (username + hashed password), created via a
  one-time `/setup` wizard on first run, session-cookie login, CSRF
  protection on every state-changing request. A security question (set
  during `/setup`, required — there's no email tied to this account to
  send a reset link through) is the recovery path via `/forgot-password`
  on the login page, rate-limited with the same exponential backoff as
  login itself; changeable anytime from Settings > Account, which also
  requires the current password for any change. A terminal-based script
  (`reset-admin.sh`/`.ps1`/`.bat`) is still there as a hard fallback if
  the security answer is forgotten too — see "Locked out?" in
  `SETUP.md`.
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
  instruction block, regardless of which provider its own session runs.
  See "AI CLI providers" in `SETUP.md`. Small colored badges (not real
  brand logos, this app fetches no external assets) show which provider
  each agent actually uses, in a stack's agent table and its diagram.
- **Setup wizard & default AI**: `/wizard` (shown once right after
  creating your admin account, or reachable anytime from Settings) walks
  through picking a provider, connecting it, and setting it as your
  default. Pre-fills new sessions and is meant to be the one that runs
  your Agent Stacks. The default picker only ever offers a provider that's
  both actually connected *and* capable of running a stack at all. Claude
  is the only one confirmed end-to-end (`orchestration_verified` in
  `providers.py`); Gemini/Codex/Kimi are offered too now that Agent Stacks
  translation exists for them (below), flagged "unverified" until someone
  actually confirms one working.
- **Per-provider usage tracking**: each of the four has a "Track usage"
  checkbox in Settings (`providers.verify_provider_key`), separate from
  the auth that runs sessions, plus a live heartbeat badge once enabled
  (connected / no key yet / key not accepted), also shown as a dashboard
  widget. Gemini/Codex/Kimi reuse the API key already running their
  sessions. Claude needs a separate Anthropic Console API key: OAuth
  (the Claude Code CLI's own login) is banned for third-party use as of
  Anthropic's 2026 policy enforcement, so there's no equivalent of the
  GitHub/GitLab OAuth flow available for pulling Claude usage data.
- **Real usage/cost numbers for Claude and Codex** (`providers.fetch_usage_cost`):
  an optional separate admin-scoped API key (Anthropic Admin key,
  OpenAI org admin key) unlocks real tokens + cost for the last 7 days
  on the dashboard's usage tile, instead of just connection status.
  Neither provider's regular API key (the one that runs sessions, or
  Claude's Console key above) can pull this, by their own design. Not
  available for Gemini (billing lives entirely in Google Cloud's own
  billing system, unreachable from an AI Studio key) or Kimi (no public
  usage API found). Anthropic's Admin API is also unavailable on
  individual (non-org) accounts.
- **Agent Stacks on other providers**: Codex CLI, Gemini CLI, and Kimi
  Code CLI have each since shipped their own native subagent-delegation
  mechanism — conceptually the same idea as Claude Code's
  `.claude/agents/*.md` + Task tool, three different formats (TOML for
  Codex, Markdown+YAML for Gemini and Kimi). `agent_formats.py` translates
  every agent this app manages into all three automatically on every
  save/delete/preset-activation, writing alongside (never replacing)
  `.claude/agents/`, which stays the one source of truth. Model/effort
  and skills are deliberately not translated (see the module's own
  docstring for why); Gemini can't delegate to other subagents at all —
  a hard limit of Gemini CLI itself. Schemas are confirmed against each
  CLI's own docs, but none of the three has been run against a real
  install by this app's own author — expect a fix cycle once real output
  is seen.
- **Multi-stack**: more than one agent team can exist at once, each tied to
  a directory via Claude Code's native per-project `.claude/agents/`
  override (`/stacks/<id>/edit` — create/edit/delete named stacks). The
  global team at `~/.claude/agents/` that still applies wherever a more
  specific stack doesn't isn't a separate system -- it's a synthetic
  `stack_id="global"` entry (`_resolve_stack()` in `app.py`) using the
  exact same routes/templates as any real stack, just without a directory
  to rename or delete.
- **Agent library, presets, and custom presets**: `/stacks/<id>/edit`'s
  "Presets & library" tab has 92 individual agents (`presets/*.md`) across
  13 divisions (Engineering, Data, Content, Sales, Marketing, Security,
  Support, Project Management, Finance, Product, Testing, Specialized,
  plus IT-ops-flavored Engineering roles), filterable by a division-chip
  UI — and 18 curated preset bundles (4-6 agents each) covering the same
  ground, also filterable. Most of the library was adapted (not copied
  verbatim) from the MIT-licensed
  [agency-agents](https://github.com/msitarzewski/agency-agents) project
  — attribution and license text in `presets/THIRD_PARTY_NOTICES.md`.
  Beyond the built-in presets, checking any combination of agents from
  the library and naming it ("Save preset") creates a **custom preset**
  of your own (`custom_presets_store.py`, instance data — survives an
  app update, unlike the bundled ones) — reusable from any stack from
  then on, deletable independently of the built-ins.
- **A stack can pick its own AI**: a stack's edit page has a "default
  provider" field — every stack (including Global, which reuses the
  existing Settings > AI providers default rather than a separate field)
  always has exactly one. Selecting that stack on "+ New session"
  auto-picks that provider and skips the manual picker entirely, which
  only ever shows for "Custom directory" (no stack, nothing to answer
  the question).
- **Clone or create a GitHub/GitLab repo directly from "+ New session"**:
  optional (Settings — OAuth App Client ID/Secret, no `.env` editing
  needed). Once connected, the GitHub/GitLab tab offers both cloning an
  existing repo (picked from a live list) and creating a brand-new one
  (name it, public/private, Cadre creates it there then clones it) — and
  the same stack/provider pickers above apply here too, so a cloned repo
  lands under a specific stack's directory (inheriting its agent team)
  instead of always a flat top-level folder. Authentication uses HTTP
  Basic auth via an embedded URL (`git_hosts.authenticated_clone_url`) —
  not a Bearer header, which git's own HTTPS transport rejects outright
  even though the same token works fine for GitHub/GitLab's REST APIs —
  and persists into the repo's own git config afterward, so `git push`/
  `git pull` run later from inside the session (by you or an agent) stay
  authenticated too, not just the initial clone. Settings shows live
  verification ("Connected as `<username>`"), not just whether a token
  happens to be saved, plus real Connect/Reconnect/Disconnect controls.
- **Workflows**: a way to run an Agent Stack's task without a person
  opening a session and typing a prompt each time — save a prompt once
  against a stack, then either click "Run now" or set a schedule (a
  cron preset, or raw cron for anything else; checked every 30s) and let
  it fire on its own. Each run either starts a fresh session (the
  default — right for almost everything, since a recurring task cares
  about current reality, not chat history) or reuses one pinned session
  for a genuinely cumulative task. Unattended mode (Claude-only, off by
  default) runs with `--dangerously-skip-permissions` so a scheduled run
  doesn't just stall at the first confirmation prompt with nobody there
  to answer it — only for a task and directory you fully trust.
- **Integrations**: a named credential (API key, token, webhook URL —
  anything an agent's own scripts need a secret to reach, not tied to
  any one service) that gets injected as an environment variable into a
  session, opt-in per stack via a checklist on that stack's edit page.
  Different from a provider's own API key (Cadre's own credential for
  running a CLI) and from Connectors below (Anthropic's own account-level
  OAuth) — this is for everything else.
- **Connectors (Gmail, Google Calendar, Google Drive)**: Claude-only,
  tied to whichever claude.ai account the `claude` CLI itself is logged
  into, not something Cadre stores credentials for. Settings > Connectors
  spins up (or reuses) a session, waits for it to be ready, and opens
  Claude Code's own `/mcp` picker automatically, then hands you a direct
  terminal link already sitting at that menu — the last few keystrokes
  happen in a real terminal, since fully automating the rest of that menu
  turned out not to be reliably scriptable after extensive testing.
- **Interactive terminal**: every session's detail page can open a real
  xterm.js terminal over a token-authed WebSocket into that session's pty,
  not just a read-only output feed — the only way to interact with
  Gemini/Codex/Kimi sessions today, since none of them has an official
  remote-control equivalent yet. A dedicated `/terminal` hub page holds a
  session sidebar (grouped by whichever Agent Stack controls each
  session's directory, matched by workdir) alongside whichever one's
  active; `/sessions/<id>/terminal` is the same terminal as its own
  bookmarkable, chrome-free page. Resizing the browser resizes the real
  pty too (`TIOCSWINSZ`), not just the on-screen character grid, so a
  full-screen program like Claude Code itself actually uses the extra
  room — capped and debounced so a burst of resize events during page
  load can't turn into overlapping, garbled redraws.
- **Terminal color themes**: 23 options (dark/light/auto plus named
  palettes — Dracula, Solarized Dark/Light, Nord, Monokai, Gruvbox Dark,
  Tokyo Night, One Dark, Catppuccin Mocha, Synthwave, Matrix, Ayu Dark,
  GitHub Dark, Cyberpunk, plus six original combos: Rose Quartz, Deep
  Forest, Abyssal, Sunset Blvd, Arctic Frost, Blood Moon), picked right on
  the terminal page itself, not buried in Settings — it's about the CLI
  inside a session, not a dashboard-wide preference. Applied to new
  sessions and retroactively to every existing one when changed
  (`terminal_theme.py`); also best-effort-mapped onto each CLI's own
  native theme system for anyone using that provider's Remote Control
  outside this app, where a real match exists in that CLI's own catalog.
- **Dashboard appearance**: separate from the terminal theme above —
  Settings > Appearance picks this dashboard's own look. Same-mechanic
  themes are grouped under one parent card with an expandable colorway
  row, rather than each color being its own top-level card: **Glow** (12
  flat-gradient colorways), **Circuit Board** (an actual PCB trace/via/
  chip pattern, 4 colorways), **Particle Drift** (4 starfield/ember/petal
  colorways), **Aurora** (standalone), **Code Rain** (6 colorways),
  **Rainfall** (6 colorways), **Lava Lamp** (3 colorways), and **Drip** (a
  goo-filtered liquid-runner effect with a stretch/snap/droplet physics
  state machine, 6 colorways — Slime, Venom, Blood, Tar, Acid, Mercury).
  42 colorways total across 8 named themes. Every colorway overrides the
  whole app's accent-color variables too, not just the background, so
  buttons/links/badges shift with it everywhere; a shared legibility
  scrim (`--content-scrim`) keeps body text readable over even the
  busiest animated backgrounds.
- **Hand off to fresh session**: retires a long/bloated session by
  creating a brand-new one in the same directory and stopping the old
  one, writing a `CLAUDE.md` continuity nudge first
  (`presets.ensure_continuity_nudge`) so the new session checks a
  `PROJECT_STATUS.md`-style file instead of needing the full prior
  conversation reloaded to pick up where it left off.
- **Skills**: one shared list (`/skills`, `~/.claude/skills/`, unlike
  agents there's no per-stack scoping) usable by every agent in every
  stack, managed via `skills_store.py`. A skill is a different mechanism
  from an agent -- packaged instructions loaded into whatever session
  invokes it, not a separate spawned worker -- one directory per skill
  (`<name>/SKILL.md`), just name/description frontmatter and a body.
  Attaching a skill to a specific agent happens on that agent's own edit
  page (a searchable checklist), which rewrites the agent's system prompt
  with an auto-generated block naming the selected skills -- not a native
  per-agent field, since nothing confirms Claude Code has one. Ships with
  20 default skills (`_DEFAULT_SKILLS` in `app.py`) spanning coding,
  DevOps, data, writing, and research; preset agents get sensible ones
  attached automatically on activation (`_AGENT_SKILL_HINTS` in
  `presets.py`), looked up against whichever skills actually exist at
  that moment rather than baked statically into the template files, so
  deleting a skill just means it's no longer attached, not a dangling
  reference.
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
- **Remote access, made discoverable**: the setup wizard's step 4
  (`/wizard`) shows whether this instance is currently reachable from
  other devices, detects a running Tailscale install and shows its IP
  directly (`network_info.py`), and points at the full walkthrough
  (Tailscale, plain LAN, or port-forwarding behind a reverse proxy) in
  `SETUP.md` — instead of that being a fact you had to already know to go
  looking for.

## What's next

- **Confirm the other-provider Agent Stacks translation for real.** The
  format-translation layer above (`agent_formats.py`) is built and
  schema-correct per each CLI's own docs, but hasn't been run against a
  real Codex/Gemini/Kimi install by anyone yet — that's the actual next
  step, not more code.

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
