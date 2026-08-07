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
        def __init__(self, args: list[str], cwd: str, extra_env: dict | None = None) -> None:
            import os

            env = {**os.environ, **extra_env} if extra_env else None
            # Same reasoning as the POSIX branch below: a pty defaults to
            # a tiny window size until something sets it, and some CLIs'
            # one-time startup banners render at whatever size was active
            # the moment they launched, never redrawing later. Giving it
            # a generous size upfront means that first render already
            # looks reasonable -- the real browser-driven resize still
            # corrects everything else once it connects.
            try:
                self._proc = winpty.PtyProcess.spawn(args, cwd=cwd, env=env, dimensions=(40, 120))
            except TypeError:
                self._proc = winpty.PtyProcess.spawn(args, cwd=cwd, env=env)
                self.resize(40, 120)

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
        def __init__(self, args: list[str], cwd: str, extra_env: dict | None = None) -> None:
            master_fd, slave_fd = pty.openpty()
            # A pty defaults to an unset/tiny window size until something
            # explicitly sets it -- and a browser doesn't get a chance to
            # (its own resize only reaches here once the terminal
            # WebSocket connects, well after the process has already
            # started). Some CLIs -- Claude Code's own welcome banner
            # among them -- render a one-time startup screen sized to
            # whatever the pty was *at that exact moment* and never
            # redraw it on a later resize, the same way any program's
            # already-printed output doesn't retroactively rewrap. Giving
            # it a generous size before the child ever starts means that
            # first render already looks reasonable on a typical desktop
            # window, instead of assuming an 80-column default -- the
            # real browser-driven resize still corrects everything else
            # once it connects, same as before.
            try:
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
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
