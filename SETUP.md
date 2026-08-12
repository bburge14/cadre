# Cadre — Setup

A web dashboard for running and managing AI coding sessions (Claude,
Gemini, Codex, or Kimi) and Agent Stacks — a directory-scoped subagent team
(Claude Code's own native `.claude/agents/` mechanism) for any project, not
just one global team, plus a shared Skills library any agent can use. This
is self-hosted, single-user software: you run your own copy on your own
machine, under your own accounts. There's no shared server and no account
system beyond the one admin login you create for yourself below.

## What's in git vs. what's yours alone

| In this repo (git) | Never in git — created on your machine |
|---|---|
| `app.py`, `auth.py`, `config.py`, `session_manager.py`, `sessions_store.py`, `agents_store.py` | `instance/` — your admin account, your sessions list, your signing key |
| `templates/`, `requirements.txt`, `VERSION` | `.env` — your local config overrides |
| `.env.example`, `SETUP.md`, `.gitignore`, `LICENSE` | `venv/` — rebuild fresh per machine, never copy |

## Prerequisites

Just two things need to already be on the machine before any setup script
below can even run — everything else (`claude`, API keys, GitHub/GitLab)
comes after and isn't needed yet:

- **Python 3.10+**, with its `venv` module actually working — check with
  `python3 --version` (`python --version` on Windows). Download:
  [python.org/downloads](https://www.python.org/downloads/). On Debian/
  Ubuntu (including minimal server images), `python3` alone isn't always
  enough — `venv` is a separate package, and `python3 -m venv` fails
  outright without it:
  ```bash
  sudo apt install python3-venv
  ```
  If setup dies right at the "Creating virtual environment..." step,
  this is almost always why.
- **Git** — needed for `git clone` on Linux/macOS (no alternative given
  there). Download: [git-scm.com/downloads](https://git-scm.com/downloads).
  Windows users can skip this entirely and download the ZIP from this
  repo's [Releases page](https://github.com/bburge14/cadre/releases)
  instead — see the Windows steps below.

Once those two are in place, the rest of this doc gets you running. Not
needed for setup itself, but you'll want them before the app is actually
useful:

- The `claude` CLI installed and working (`claude --version`), logged into
  your own Anthropic account (`claude`, then `/login`) on a Pro, Max, Team,
  or Enterprise plan — Remote Control isn't available on API-key-only
  setups. Install: [docs.claude.com/en/docs/claude-code/setup](https://docs.claude.com/en/docs/claude-code/setup).
- On Linux, if you want this running as an always-on background service:
  `systemd --user` (already present on basically every modern distro).
- Runs on Linux, macOS, and Windows. The two processes (below) use a real
  platform-native pseudo-terminal either way — Python's `pty` module on
  Linux/macOS, `pywinpty` (wraps Windows' ConPTY) on Windows — installed
  automatically by `requirements.txt` on whichever OS you're on.

## Steps (Linux / macOS)

1. **Get the code**:
   ```bash
   git clone https://github.com/bburge14/cadre ~/.claude/cadre
   cd ~/.claude/cadre
   ```

2. **Run the setup script** — `./linux/setup.sh` on Linux, `./macos/setup.sh`
   on macOS. Each creates the virtual environment, installs everything from
   `requirements.txt`, and drops a double-clickable "Start Cadre" launcher
   on your Desktop (skipped with a message if you don't have a Desktop
   folder — headless boxes, servers, etc.). Safe to re-run
   any time (e.g. after a `git pull` that changed `requirements.txt`).

   Prefer doing it by hand, or the script can't run for some reason? Same
   two commands either script runs under the hood:
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

4. **Run it** — double-click the Desktop launcher the setup script created,
   or from a terminal:
   ```bash
   ./linux/start.sh    # or ./macos/start.sh on macOS
   ```
   Either way this is just `./venv/bin/python app.py` with a couple of
   friendly messages around it — run that directly if you'd rather. You
   should see `Running on http://127.0.0.1:7420` (or whatever host/port you
   configured).

5. **Open it in a browser** at that address. First visit should redirect
   you to an account-creation page — pick a username and password (this is
   the only account this instance will ever have). After creating it,
   you're automatically logged in and land on the setup wizard — pick
   which AI you use, connect it (Claude: create a session and run
   `/login`; Gemini/Codex/Kimi: paste an API key), and set it as your
   default. "Skip for now" if you'd rather do this later — it's always
   reachable again from Settings. Either way you land on the dashboard
   next — Sessions at the top, your Agent Stacks below it (empty at
   first, with a "+ New stack" button). That's success.

6. **Create a stack** (or skip to "back to dashboard" and manage agents
   one at a time instead — see below). A stack is a directory's own
   `.claude/agents/` team: pick a name, an absolute directory path (created
   automatically if it doesn't exist — "Browse…" next to the field opens a
   folder picker if you'd rather click through than type one), and either
   click a preset (18 available, filterable by division — Engineering,
   Data, Content, Sales, Marketing, Security, Support, Project Management,
   Finance, Product, Testing, and general Business Operations/HR/Legal) or
   check individual agents from the library (92 total, same filter). Not
   sure which fits yet? Generalist is a reasonable default — a bit of
   code, writing, research, and analysis, nothing deeply specialized.
   Checking any combination from the library and naming it ("Save
   preset") turns it into a preset of your own, reusable from any stack
   afterward. Only sessions
   rooted in that directory (or a subdirectory of it) pick up this team —
   this is Claude Code's own native per-project agent override, not
   anything this app invents. Make as many stacks as you want, one per
   project/purpose.
   There's also one **global** team, at `~/.claude/agents/` and
   `~/.claude/skills/` — it applies to any session *not* covered by a more
   specific stack. It's not a separate page; it's the "Global (default)"
   row always pinned at the top of the same Agent Stacks list, with the
   same Edit/Diagram/agents-table/skills-table as any real stack, just
   without a directory to rename or delete.

7. **Create your first session** via "+ New session" — give it a label, a
   provider (Claude, Gemini, Codex, or Kimi — see "AI CLI providers"
   below), and a working directory that already exists on this machine,
   e.g. a project you're working on (point it at one of your stacks'
   directories to use that team). For Claude, it launches with Remote
   Control enabled — the session's detail page shows the connect URL/QR
   once it's up. Every provider also gets an interactive terminal right in
   the dashboard ("Open terminal" on the session's page) — useful for
   Claude too, and the only way to interact with Gemini/Codex/Kimi sessions
   from here today, since none of them has an official remote-control
   equivalent yet.

## Steps (Windows)

1. **Get the code**. Either `git clone`, or download the ZIP from the
   repo's Releases page and extract it somewhere — either way you end up
   with a folder containing `app.py`, `windows\`, etc. Where you extract
   the ZIP doesn't matter (Downloads is fine) — the next step relocates it
   automatically.
   ```powershell
   git clone https://github.com/bburge14/cadre $env:USERPROFILE\cadre
   cd $env:USERPROFILE\cadre
   ```

2. **Double-click `windows\setup.bat`** (or run it from a terminal). If
   you extracted a ZIP (no `.git\`), this first moves the whole folder to
   a stable home at `%LocalAppData%\Programs\Cadre` and re-launches setup
   from there — so it isn't left depending on a Downloads folder that
   might get cleaned out later. (A `git clone` is left exactly where you
   put it, since moving it would break `git pull`/`update.bat`.) Either
   way, it then creates the virtual environment, installs everything from
   `requirements.txt` — the one step that's easy to miss if you skip
   straight to running the app — and creates a "Start Cadre" shortcut on
   your Desktop pointing at `windows\start.bat`. It also
   installs `pywinpty`, which needs a working C++ toolchain to build from
   source on some setups — if that step fails, install the
   [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
   (or Visual Studio Community with the "Desktop development with C++"
   workload) and re-run `windows\setup.bat`. If only the shortcut step
   fails (rare — PowerShell execution policy on some locked-down machines),
   everything else still works; just run `windows\start.bat` directly or
   make the shortcut yourself.

3. **(Optional) copy the config template** — same as Linux/macOS:
   ```powershell
   copy .env.example .env
   ```

4. **Double-click `windows\start.bat`** to launch the dashboard (same as
   running `venv\Scripts\python app.py` yourself — this is just
   double-clickable, and it's what you'd point a desktop shortcut at).
   Same as Linux/macOS from here — open the printed address in a browser,
   create your account, land on Agent Stacks, create your first stack (or
   skip to the dashboard), create your first session.

For always-on background operation instead of a terminal window you leave
open, see "Running it as an always-on background service (Windows)" below.

## Connecting GitHub / GitLab (optional)

You don't need to touch `.env` for this — go to **Settings** (top-right of
the dashboard once logged in). It shows you the exact callback URL to
register, and everything you paste in there (Client ID/Secret, GitLab base
URL, where repos get cloned to) is saved immediately, no restart required:

1. Register an OAuth App: github.com/settings/developers (GitHub) or, on
   GitLab, your avatar (top right) → **Edit profile** → **Access** (left
   sidebar) → Applications → Add new application — on your own profile,
   not the admin area. Use the callback URL shown on the Settings page,
   check scope `read_api`/`read_repository` for GitHub's `repo` scope
   equivalent — for GitLab specifically, use the single `api` scope
   (full read/write; `read_api` alone 403s on creating a repo, since
   it's read-only by design) — and leave "Confidential" checked.
2. Paste the Client ID/Secret into Settings and save.
3. Back on "+ New session," the GitHub/GitLab tab now shows a "Connect
   your account" link — click it, authorize on their site, and you're
   taken back here. From then on that tab offers both cloning an
   existing repo (picked from a live list) and creating a brand-new one
   (name it, public/private — Cadre creates it there, then clones it).
   The stack/provider pickers above the source tabs apply to both, so a
   cloned/created repo can land under a specific stack's directory
   (inheriting its agent team) instead of always a flat top-level folder.
4. Settings shows live status ("Connected as `<username>`," not just
   whether a token happens to be saved) plus Connect/Reconnect/Disconnect
   controls — Reconnect re-authorizes from scratch, useful if you ever
   change the app's registered scopes.

**Reached from more than one address** (localhost, a LAN IP, Tailscale)?
GitHub/GitLab OAuth apps only accept one exact, registered callback URL,
but Cadre normally computes it from whatever address is in your browser's
bar at the moment — which breaks (GitHub's "the redirect_uri is not
associated with this application" page) the moment you click Connect from
a different address than the one you registered. Settings > **Public base
URL** pins it to one fixed address regardless of which address the click
actually came from — set it to whichever one you registered.

Skip this section entirely if you only ever plan to point sessions at
directories already on this machine — nothing else depends on it.

## AI CLI providers (Claude / Gemini / Codex / Kimi)

The setup wizard (`/wizard`, also linked from Settings) walks through
connecting one of these step by step; this section is the manual/reference
version of the same thing, and covers per-agent delegation, which the
wizard doesn't.

Every agent in every stack is still a **Claude Code subagent** — that part
isn't optional, and it's why there's no "Claude" row in the API-key list
below. What you're logged into is the `claude` CLI itself, the same one
this whole app is built on. There's nothing to configure for it in
Settings; instead, Settings tells you your actual state:

- **`claude` not found on this machine** — you have an Anthropic account
  but not the CLI installed. That's a separate one-time step this app
  can't do for you (`npm install -g @anthropic-ai/claude-code`, see
  [docs.claude.com](https://docs.claude.com/en/docs/claude-code/setup)).
- **Installed but not logged in yet** — create a session, open its
  terminal, and run `/login` there. It's a normal part of using `claude`,
  not a separate flow this app implements.
- **Installed and logged in** — you're set, nothing to do.

Gemini, Codex, and Kimi are optional and **API-key only** here — go to
**Settings** and paste a key for whichever you use. Unlike GitHub/GitLab,
there's no OAuth app a third party can register for these three (each
CLI's account login is baked into its own binary), so a key is the only
auth path this dashboard offers them. Settings also flags whether each
CLI is even found on your `PATH` — if you installed one via `npm`/`nvm`,
make sure whatever runs `session_daemon.py` (a login shell, or your
service's `PATH=` line if running as a service) can actually see it.

These three don't replace Claude anywhere — what they're for is **per-agent
delegation**: editing an agent (`+ New agent` / edit an existing one) lets
you pick a "primary AI for this agent's actual work." Doing so rewrites
that agent's instructions with an auto-generated block telling it to shell
out to the chosen provider's non-interactive mode (`gemini -p "..."`,
`codex exec "..."`, `kimi -p "..."`) and treat that as its real answer. The
agent itself is still a Claude Code subagent doing the orchestrating —
this doesn't reduce Claude usage, it's for cases where you specifically
want a different model's output on a given agent's tasks.

### Agent Stacks on Gemini/Codex/Kimi

Codex CLI, Gemini CLI, and Kimi Code CLI have each since shipped their own
native subagent mechanism — the same idea as Claude Code's
`.claude/agents/*.md`, three different formats. Every time you save,
delete, or activate an agent, Cadre also writes it out in all three
(`.codex/agents/*.toml`, `.gemini/agents/*.md`, `.kimi-code/agents/*.md`,
right alongside `.claude/agents/`, which stays the one source of truth) —
so once you've connected one of these as your default, its own binary
should be able to read the same team you built here directly. **Nobody has
actually confirmed this working against a real install yet** — schemas
are correct per each CLI's own docs, but that's not the same thing as
tested. If you try one and something's off, that's the current state of
this feature, not a regression.

### When a session hits a usage/rate limit

If a session's underlying CLI hits its own usage limit (Claude's 5-hour/
weekly cap) or a rate/quota error (common on API-key-only Gemini/Codex/
Kimi setups), the dashboard notices and flags it — an orange "limit hit"
tag on the session list, a banner with the actual message on the session's
detail page, and a browser notification if you're looking at that page
when it happens and have granted notification permission. This is best-
effort text matching on the CLI's own output, not something this app
controls — it clears itself the next time you restart that session.

## Two processes, on purpose

This app is actually two pieces:

- **`app.py`** — the web dashboard (auth, templates, agent editing). You'll
  restart/redeploy this often as you make changes.
- **`session_daemon.py`** — a separate, much simpler process that actually
  owns each Claude Code session's terminal (a pty) and keeps it alive. It
  talks to `app.py` over a TCP loopback connection (`127.0.0.1`, port from
  `CADRE_DAEMON_PORT` in `.env`, default `7421`) — not exposed
  beyond this machine, and a plain TCP port rather than a Unix domain
  socket specifically so this works identically on Windows.

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

cat > ~/.config/systemd/user/cadre-daemon.service <<'EOF'
[Unit]
Description=Cadre - session daemon (owns pty/process lifecycle)

[Service]
Type=simple
WorkingDirectory=%h/.claude/cadre
ExecStart=%h/.claude/cadre/venv/bin/python session_daemon.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

cat > ~/.config/systemd/user/cadre-app.service <<'EOF'
[Unit]
Description=Cadre
Wants=cadre-daemon.service
After=cadre-daemon.service

[Service]
Type=simple
WorkingDirectory=%h/.claude/cadre
ExecStart=%h/.claude/cadre/venv/bin/python app.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now cadre-daemon.service cadre-app.service
loginctl enable-linger "$USER"   # keeps both running even when you're logged out
```

Check both came up: `systemctl --user status cadre-daemon.service
cadre-app.service` should show `active (running)` for each.

On macOS, there's no systemd — just run `./venv/bin/python app.py` in a
terminal you leave open, or wrap it in your own `launchd` plist if you want
it persistent.

## Locked out? Resetting the admin account

The password is hashed one-way (`werkzeug.security.generate_password_hash`)
the moment it's set — nobody, including whoever built this, can recover a
forgotten one from the stored file. What you *can* do is reset it:

```bash
./linux/reset-admin.sh     # or ./macos/reset-admin.sh
```
```powershell
windows\reset-admin.bat
```

Deletes only `instance/admin.json` — your sessions, agent stacks, skills,
and settings are all separate files and untouched. No restart needed
either: whether an admin account exists is checked fresh on every request,
so the very next page load redirects straight to `/setup` to create a new
one. `-y`/`--yes` skips the confirmation prompt.

## Uninstalling / resetting for a clean re-test

To mimic a genuinely fresh install (useful when testing on a second
machine, or just to rule out leftover local state), each OS has an
uninstall script alongside its setup script:

```bash
./linux/uninstall.sh     # or ./macos/uninstall.sh
```
```powershell
windows\uninstall.bat
```

Each stops the dashboard/daemon (systemd services or scheduled tasks, if
you registered them; otherwise just the running processes) and deletes
`venv/`, `instance/` (your admin account, sessions list, agent stacks,
settings), `.env`, and the Desktop launcher — then prompts for
confirmation before doing any of it (`-y`/`--yes` skips the prompt, for
scripted repeat testing). **Never touched**: the source code itself,
`~/.claude/agents/` (your global agent team), and every stack's own
project directory — this only removes what the setup script created.

Run the matching `setup.sh`/`setup.bat` again afterward for a clean
first-run experience, `/setup` account creation and all.

Since stopping the daemon ends any Claude Code sessions it's currently
holding open, each script double-checks (by comparing the registered
service/task's own working directory against the checkout you're running
it from) that it's only ever touching *this* install's services — a second
checkout elsewhere, or a copy used for testing, can't reach across and
stop a different one.

## Updating

**Settings** shows the version you're running (`VERSION` in the repo).
"Check for updates" asks GitHub's public releases API whether a newer one
exists; if so, an "Update now" button appears right there — click it and
it updates in place (`git pull` for a git-clone install; for a
ZIP-downloaded install, downloads and applies the latest release's source
ZIP directly, merging it into the existing directory so `venv/`,
`instance/`, and `.env` — none of which exist in a fresh release ZIP — are
never touched), reinstalls `requirements.txt` (in case it changed), and —
using the same working-directory match as the uninstall scripts —
restarts the **dashboard only** if this checkout owns a registered
service/task, then reloads the page automatically once it's back. The
session daemon is deliberately never touched by this, since restarting it
ends any live Claude Code sessions it's holding open; if a given update
specifically touched `session_daemon.py`, restart that yourself once
you're ready (or just wait for its next natural restart). If nothing's
registered (or on macOS, where there's no services concept here at all),
it tells you to restart the dashboard by hand instead of trying to.

A terminal-based equivalent is also available, but **git-clone installs
only** (unlike the in-app button, it doesn't know how to fetch/apply a ZIP):

```bash
./linux/update.sh     # or ./macos/update.sh
```
```powershell
windows\update.bat
```

## Running it as an always-on background service (Windows)

There's no systemd on Windows, but the same idea works via Task Scheduler.
From a normal (non-admin) PowerShell prompt, after the venv is set up:

```powershell
powershell -ExecutionPolicy Bypass -File windows\install-services.ps1
```

This registers two scheduled tasks (one per process, mirroring the systemd
setup above) that start automatically at login and restart on failure, and
starts both immediately. Check status with:
```powershell
Get-ScheduledTask -TaskName "Cadre-*"
```
To remove them later: `windows\uninstall-services.ps1` (same pattern, does
not touch `instance/` or `.env`).

## Building the actual Windows `.exe` installer

The steps above (clone + venv + `pip install`) work today and are the
fastest path to running this on Windows. A real double-click installer
(`Setup.exe`, no Python/git required on the target machine) is also
buildable, but **this must be built on a Windows machine** — PyInstaller
doesn't cross-compile from Linux/macOS, so this could only be written and
documented from here, not actually produced or tested. Treat it as
unverified until it's been run for real:

1. One-time: `venv\Scripts\pip install pyinstaller`, and install
   [Inno Setup](https://jrsoftware.org/isinfo.php) (free) so `ISCC.exe` is
   on your `PATH`.
2. `powershell -ExecutionPolicy Bypass -File windows\build.ps1` — builds
   `CadreApp.exe` and `CadreDaemon.exe` via
   PyInstaller (`windows\app.spec` / `windows\daemon.spec`), then wraps
   them into `windows\installer-output\Cadre-Setup-*.exe`
   via Inno Setup (`windows\installer.iss`).
3. Running that `Setup.exe` installs to `%LOCALAPPDATA%\Programs\Cadre`
   (no admin rights needed), registers the same two scheduled tasks as
   "Running it as an always-on background service (Windows)" above, and
   opens the dashboard in your browser when done.

If something breaks partway through the freeze (a missing bundled file, an
import PyInstaller's static analysis didn't catch), that's exactly the kind
of thing that only surfaces once actually run — expect a debugging pass
here, most likely in `windows/app.spec`'s `datas`/`hiddenimports` lists.

## Reaching it from another device

By default this only listens on `127.0.0.1` — reachable from this machine
alone. Getting it onto your phone or another computer takes two steps no
matter which option below you pick:

1. Set `CADRE_HOST=0.0.0.0` in `.env` — this makes the app listen on every
   network interface on this machine, not just the loopback one.
2. Restart it: `sudo systemctl --user restart cadre-app.service` (Linux),
   or however you normally restart it on your platform (see "Running it as
   an always-on background service" above).

That alone is enough on a trusted home LAN — anything else on the same
network can now reach `http://<this-machine's-LAN-IP>:7420`. The wizard's
step 4 (`/wizard`) shows whether `CADRE_HOST` is currently `0.0.0.0` or
still the default, so you can confirm the setting took without digging
through `.env` by hand.

### Option A: Tailscale (recommended)

[Tailscale](https://tailscale.com) puts this machine and your other
devices (phone, laptop) on their own private network, reachable by each
other from anywhere with an internet connection — no port-forwarding, no
public exposure, no dynamic DNS to maintain.

1. Install it on this machine and on whatever device you want to reach the
   dashboard from: [tailscale.com/download](https://tailscale.com/download).
2. Sign in on both (`tailscale up` on this machine if it's headless) — same
   Tailscale account on both ends.
3. Find this machine's Tailscale IP: `tailscale ip -4`, or check
   [login.tailscale.com/admin/machines](https://login.tailscale.com/admin/machines).
   The wizard's step 4 also shows this automatically once Tailscale is
   installed and running.
4. Set `CADRE_HOST=0.0.0.0` and restart (above), then open
   `http://<tailscale-ip>:7420` from the other device. It works over
   cellular data too, not just when both devices are on the same Wi-Fi.

### Option B: plain LAN

No install needed beyond step 1/2 above — just use this machine's regular
LAN IP (`ip addr` / `ipconfig`) instead of a Tailscale one. Only reachable
from devices on the same local network, and only while this machine's IP
doesn't change (most home routers hand out the same IP by default, but
don't guarantee it).

### Option C: port forwarding onto the open internet — advanced, not recommended without TLS

Forwarding a router port straight to this app puts it on the public
internet. **Do not do this without a reverse proxy (Caddy, nginx, etc.) in
front of it terminating real TLS first.** This is a plain-HTTP dev server
underneath; the login/CSRF protection built into the app is not a
substitute for encrypting the connection itself, and an unencrypted
session cookie on the open internet can be intercepted. Leave
`CADRE_HOST` at its default (`127.0.0.1`) for this option — only the
proxy needs to be reachable from outside, not this app directly.

You'll need a domain name (or subdomain) pointed at your home's public IP
— a dynamic DNS provider (DuckDNS, No-IP, etc.) if that IP isn't static —
since automatic HTTPS needs a real hostname to issue a certificate for.
[Caddy](https://caddyserver.com/docs/install) is the least setup of the
common options:

1. Install it (per-OS instructions at the link above).
2. Create a `Caddyfile` next to wherever you run it from:
   ```
   your-domain.example.com {
       reverse_proxy 127.0.0.1:7420
   }
   ```
3. Run it: `caddy run` (or install it as a service — see Caddy's own
   docs). It requests and renews the certificate automatically the first
   time it starts.
4. On your router, forward ports `80` and `443` to this machine (Caddy
   needs port 80 briefly for the certificate challenge, then serves
   everything over 443) — **not** port 7420.

From there, `https://your-domain.example.com` reaches Cadre through
Caddy, TLS included. This is genuinely more setup than the Tailscale
option above (a domain, DNS, router configuration, a second process to
keep running) — worth it only if you specifically need Cadre reachable by
something that can't run Tailscale itself.

## Per-machine settings to double check

- `CLAUDE_BIN` in `.env` — only needed if `claude` isn't on the `PATH` that
  this app's Python process sees (rare; matters more if you're running it
  as a service under a minimal environment).
- `CLAUDE_AGENTS_DIR` in `.env` — only needed if you want this instance to
  manage a subagent-definitions directory other than the standard
  `~/.claude/agents`.
- `CADRE_DAEMON_PORT` in `.env` — only needed if `7421` is already
  in use by something else on this machine.
