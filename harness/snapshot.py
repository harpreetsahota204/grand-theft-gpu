"""Per-turn evidence: a git commit of the workspace and a screenshot of the game.

`harness.runner` calls `commit` and `screenshot` after every turn. The commits
give a timeline to score against the tier checklist; the screenshots give
footage for the video and tell us when the first playable build appeared.
"""

import functools
import subprocess
import threading
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import ConsoleMessage, sync_playwright

from harness.config import GAME_ENTRY, SCREENSHOT_SETTLE_MS

# Headless Chromium needs software GL to render WebGL (three.js) games.
CHROMIUM_ARGS: list[str] = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


@dataclass(frozen=True)
class ShotResult:
    """Outcome of screenshotting the game after a turn.

    Attributes:
        has_entry: whether the workspace has the game entry file yet
        loaded: whether the page loaded without throwing
        console_errors: console errors and uncaught exceptions seen while settling
    """

    has_entry: bool
    loaded: bool
    console_errors: list[str]


def init_workspace(workspace: Path) -> None:
    """Creates the contender's workspace as an empty git repo with a fixed identity.

    Args:
        workspace: folder the model builds in; created if missing
    """
    workspace.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    # A local identity so commits never depend on (or leak) the user's git config.
    for key, value in (("user.name", "race-harness"), ("user.email", "harness@localhost")):
        subprocess.run(["git", "config", key, value], cwd=workspace, check=True)


def commit(workspace: Path, message: str) -> str:
    """Commits everything in the workspace, even if nothing changed.

    Args:
        workspace: the contender's git repo
        message: commit message, e.g. "turn 3"

    Returns:
        the new commit's SHA
    """
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True)
    # --allow-empty keeps one commit per turn so turn N always maps to commit N.
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "--no-verify", "-m", message],
        cwd=workspace,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace, capture_output=True, text=True, check=True
    )
    return sha.stdout.strip()


def screenshot(workspace: Path, out_png: Path) -> ShotResult:
    """Serves the workspace over HTTP and screenshots the game entry page.

    The page is served (not opened via file://) because ES module imports, which
    most three.js builds use, are blocked on file URLs.

    Args:
        workspace: folder containing the game
        out_png: where to write the 1280x720 screenshot

    Returns:
        whether the entry exists, whether it loaded, and any console errors
    """
    if not (workspace / GAME_ENTRY).exists():
        return ShotResult(has_entry=False, loaded=False, console_errors=[])

    # Port 0 lets the OS pick a free port, so both contenders can snapshot at once.
    handler = functools.partial(_QuietHandler, directory=str(workspace))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/{GAME_ENTRY}"

    errors: list[str] = []
    loaded = False

    def on_console(msg: ConsoleMessage) -> None:
        """Keeps console errors; drops log/info/warning noise."""
        if msg.type == "error":
            errors.append(msg.text)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.on("console", on_console)
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                page.goto(url, wait_until="load", timeout=15_000)
                loaded = True
                # Give the game loop time to render a few frames before capture.
                page.wait_for_timeout(SCREENSHOT_SETTLE_MS)
                out_png.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out_png))
            except Exception as exc:  # noqa: BLE001 - a broken build is data, not a harness crash
                errors.append(f"harness: {exc}")
            browser.close()
    finally:
        server.shutdown()

    return ShotResult(has_entry=True, loaded=loaded, console_errors=errors)


class _QuietHandler(SimpleHTTPRequestHandler):
    """Static file handler that doesn't spam the race console with access logs."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        """Drops access log lines."""
