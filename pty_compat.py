"""Cross-platform pseudo-terminal + process lookup/termination.

Linux/macOS: Python's stdlib `pty` module + subprocess with `os.setsid`.
Windows: `pywinpty` (wraps the native ConPTY API) -- there is no `pty`
module and no process-group/setsid equivalent on Windows, so this is a
real platform split, not just a portability shim. `claude`'s Remote
Control mode needs a real terminal either way; this is what provides one.
"""
from __future__ import annotations

import sys

import psutil

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import winpty  # pywinpty package; import name is winpty

    class PtySession:
        def __init__(
            self, args: list[str], cwd: str, extra_env: dict | None = None,
            cols: int | None = None, rows: int | None = None,
        ) -> None:
            import os

            env = {**os.environ, **extra_env} if extra_env else None
            # Same reasoning as the POSIX branch below: a pty defaults to
            # a tiny window size until something sets it, and some CLIs'
            # one-time startup banners render at whatever size was active
            # the moment they launched, never redrawing later. cols/rows
            # let a caller that already knows the real connecting
            # browser's size (starting/restarting from an already-open
            # terminal view) pass it straight through instead of
            # guessing -- falls back to a best-effort guess biased toward
            # a typical wide desktop window when no caller-known size is
            # available (e.g. starting from the plain sessions list,
            # independent of any terminal WebSocket connection).
            rows, cols = rows or 50, cols or 180
            try:
                self._proc = winpty.PtyProcess.spawn(args, cwd=cwd, env=env, dimensions=(rows, cols))
            except TypeError:
                self._proc = winpty.PtyProcess.spawn(args, cwd=cwd, env=env)
                self.resize(rows, cols)

        def read(self, size: int = 4096) -> bytes:
            try:
                text = self._proc.read(size)
            except EOFError:
                return b""
            return text.encode("utf-8", errors="replace") if text else b""

        def write(self, data: bytes) -> None:
            try:
                self._proc.write(data.decode("utf-8", errors="replace"))
            except (OSError, ValueError):
                pass

        def is_alive(self) -> bool:
            return self._proc.isalive()

        @property
        def pid(self) -> int:
            return self._proc.pid

        def resize(self, rows: int, cols: int) -> None:
            try:
                self._proc.setwinsize(rows, cols)
            except Exception:
                pass

        def terminate(self) -> None:
            try:
                self._proc.terminate(force=True)
            except Exception:
                pass

else:
    import fcntl
    import os
    import pty
    import signal
    import struct
    import subprocess
    import termios

    class PtySession:
        def __init__(
            self, args: list[str], cwd: str, extra_env: dict | None = None,
            cols: int | None = None, rows: int | None = None,
        ) -> None:
            master_fd, slave_fd = pty.openpty()
            # A pty defaults to an unset/tiny window size until something
            # explicitly sets it. Some CLIs -- Claude Code's own welcome
            # banner and a --resume'd session's recap among them -- render
            # a one-time startup screen sized to whatever the pty was *at
            # that exact moment* and never redraw it on a later resize,
            # the same way any program's already-printed output doesn't
            # retroactively rewrap. This is set here, before
            # subprocess.Popen() below ever runs, so there's no race
            # against the child's own first paint the way there would be
            # if a resize arrived only after the child had already started
            # writing -- cols/rows let a caller that already knows the
            # real connecting browser's size (starting/restarting from an
            # already-open terminal view) pass it straight through instead
            # of guessing, so that first render is actually correct
            # instead of merely "reasonable," and instead of silently
            # baking stale wrong-width content into this session's
            # backlog forever (see session_daemon.py's MAX_BACKLOG_CHARS
            # comment for what that costs). Falls back to a best-effort
            # guess biased toward a typical wide desktop window when no
            # caller-known size is available (e.g. starting from the
            # plain sessions list, independent of any terminal WebSocket
            # connection) -- the real browser-driven resize still corrects
            # everything else once it connects, same as before.
            rows, cols = rows or 50, cols or 180
            try:
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass
            env = {**os.environ, **extra_env} if extra_env else None
            self._proc = subprocess.Popen(
                args, cwd=cwd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                preexec_fn=os.setsid, close_fds=True, env=env,
            )
            os.close(slave_fd)
            self._master_fd = master_fd

        def read(self, size: int = 4096) -> bytes:
            try:
                return os.read(self._master_fd, size)
            except OSError:
                return b""

        def write(self, data: bytes) -> None:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass

        def is_alive(self) -> bool:
            return self._proc.poll() is None

        @property
        def pid(self) -> int:
            return self._proc.pid

        def resize(self, rows: int, cols: int) -> None:
            # TIOCSWINSZ on the master fd is what actually changes what a
            # full-screen TUI (vim, htop, or the CLI itself) thinks its
            # window is -- the kernel sends SIGWINCH to the pty's
            # foreground process group on its own once this is set, no
            # explicit signal needed.
            try:
                fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass

        def terminate(self) -> None:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                os.close(self._master_fd)
            except OSError:
                pass


def find_pids_by_arg(needle: str, exclude_pid: int | None = None) -> list[int]:
    """PIDs of any process (ours or started elsewhere -- a desktop icon,
    a manual terminal) whose command line contains `needle` (a session
    UUID). Uses psutil instead of `pgrep` so this works identically on
    Windows, and doesn't depend on `pgrep` being installed on Linux either.
    """
    matches = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if exclude_pid is not None and proc.info["pid"] == exclude_pid:
            continue
        if any(needle in part for part in cmdline):
            matches.append(proc.info["pid"])
    return matches


def kill_pid(pid: int) -> None:
    try:
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=5)
        except psutil.TimeoutExpired:
            p.kill()
    except psutil.NoSuchProcess:
        pass
