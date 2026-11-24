"""Checks that this machine has everything needed to run a race.

Run it first on a fresh clone; it prints one line per prerequisite and exits
non-zero if anything is missing. It only reads versions and status;
it never changes configuration.

Called by `buildoff doctor` (see `harness.cli`):
    uv run buildoff doctor
"""

import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from harness import sandbox


def run(cmd: list[str]) -> str | None:
    """Runs a command and returns its first output line, or None if it fails."""
    if shutil.which(cmd[0]) is None and not Path(cmd[0]).exists():
        return None
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or proc.stderr).strip().splitlines()
    return lines[0] if lines else ""


def check_macos() -> str | None:
    """Live viewers open Terminal windows via osascript, so the race needs macOS."""
    return platform.mac_ver()[0] or None


def check_nexus_connected() -> str | None:
    """Nexus must be logged in and routing Claude Code through Fireworks."""
    out = subprocess.run(
        ["nexus", "claude", "status"], capture_output=True, text=True, timeout=60
    ).stdout
    return "connected" if "Connection: on" in out else None


def check_chromium() -> str | None:
    """Playwright's Chromium takes the per-turn screenshots."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).name if pw.chromium.executable_path else None
    except Exception:  # noqa: BLE001 - any failure here means "not installed"
        return None


def check_python() -> str | None:
    """The harness uses 3.12 syntax; uv picks this from .python-version."""
    return platform.python_version() if sys.version_info >= (3, 12) else None


class Check(NamedTuple):
    """One prerequisite.

    Attributes:
        name: what is being checked, as printed
        probe: returns a short "found" string, or None if missing
        fix: how to install or fix it
    """

    name: str
    probe: Callable[[], str | None]
    fix: str


CHECKS: list[Check] = [
    Check("macOS", check_macos, "races need macOS (sandbox-exec isolates each model)"),
    Check("Python 3.12+", check_python, "uv sync"),
    Check(
        "Claude Code",
        lambda: run(["claude", "--version"]),
        "install from https://claude.com/claude-code (2.1.281+)",
    ),
    Check(
        "Nexus CLI",
        lambda: run(["nexus", "--version"]),
        "curl -fsSL https://nexus.fireworks.ai/install.sh | bash",
    ),
    Check("Nexus connected", check_nexus_connected, "nexus login && nexus claude"),
    Check("git", lambda: run(["git", "--version"]), "xcode-select --install"),
    Check(
        "sandbox-exec (contender isolation)",
        lambda: None if sandbox.check() else "ok",
        "races need macOS's /usr/bin/sandbox-exec",
    ),
    Check("Chromium (Playwright)", check_chromium, "uv run playwright install chromium"),
    Check("Node.js (base game)", lambda: run(["node", "--version"]), "brew install node"),
]


def run_checks() -> int:
    """Runs every check and prints one line each.

    Returns:
        process exit code: 1 if anything is missing, else 0
    """
    missing = False
    for check in CHECKS:
        try:
            found = check.probe()
        except (OSError, subprocess.SubprocessError):
            found = None
        if found:
            print(f"  ok    {check.name}: {found}")
        else:
            print(f"  MISS  {check.name}  ->  {check.fix}")
            missing = True
    return 1 if missing else 0
