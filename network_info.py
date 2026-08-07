from __future__ import annotations

import subprocess

_TAILSCALE_TIMEOUT_S = 2


def tailscale_status() -> dict:
    """Best-effort probe of the `tailscale` CLI on this machine.

    Never raises -- any failure (not installed, not running, timeout) just
    means less information to show, not a broken page.
    """
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=_TAILSCALE_TIMEOUT_S,
        )
    except FileNotFoundError:
        return {"installed": False, "running": False, "ip": None}
    except (OSError, subprocess.SubprocessError):
        return {"installed": True, "running": False, "ip": None}

    ip = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    return {"installed": True, "running": result.returncode == 0 and bool(ip), "ip": ip if result.returncode == 0 else None}
