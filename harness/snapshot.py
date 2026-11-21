"""Per-turn evidence: a git commit, a Vite build, and a screenshot of the game.

`harness.runner` calls `commit`, `build` and `screenshot` after every turn. The
commits give a timeline to score against the tier checklist; the build tells us
whether the game still compiles; the screenshots give footage for the video and
tell us when the first playable build appeared.
"""

import contextlib
import functools
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import ConsoleMessage, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from harness.config import GAME_ENTRY, SCREENSHOT_SETTLE_MS

# Headless Chromium needs software GL to render WebGL (three.js) games.
CHROMIUM_ARGS: list[str] = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]


# Characters of build output kept when a build fails, enough to show the error.
BUILD_LOG_TAIL_CHARS: int = 2000
BUILD_TIMEOUT_S: int = 600

# Upper bound on waiting for the game's asset downloads after page load. A game
# that streams forever still gets screenshotted once this expires.
NETWORK_IDLE_TIMEOUT_MS: int = 60_000

# Time for frames to render after the click that starts play.
AFTER_CLICK_MS: int = 3000

# Headless Chromium never grants pointer lock, so games that gate play behind
# "click to play" (requestPointerLock) stay on their menu forever. This stub,
# installed before any page script runs, makes the standard pointer-lock API
# succeed on click. It only touches the browser API, not game code, so it works
# for whatever start screen either model builds.
POINTER_LOCK_SHIM: str = """
(() => {
  let locked = null;
  Object.defineProperty(Document.prototype, "pointerLockElement", {
    get() { return locked; }, configurable: true,
  });
  Element.prototype.requestPointerLock = function () {
    locked = this;
    document.dispatchEvent(new Event("pointerlockchange"));
    return Promise.resolve();
  };
  Document.prototype.exitPointerLock = function () {
    locked = null;
    document.dispatchEvent(new Event("pointerlockchange"));
  };
})();
"""


@dataclass(frozen=True)
class ShotResult:
    """Outcome of screenshotting the game after a turn.

    Attributes:
        has_entry: whether the built site has the game entry file
        loaded: whether the page loaded without throwing
        console_errors: console errors and uncaught exceptions seen while settling
    """

    has_entry: bool
    loaded: bool
    console_errors: list[str]


@dataclass(frozen=True)
class BuildResult:
    """Outcome of building the game after a turn.

    Attributes:
        ok: whether `npm install` and `npm run build` both succeeded
        log_tail: the end of the combined output when the build failed, else ""
    """

    ok: bool
    log_tail: str


def build(workspace: Path) -> BuildResult:
    """Installs dependencies and runs the Vite production build.

    `npm install` runs every turn because the model may have added packages;
    with nothing new it finishes in a second or two.

    Args:
        workspace: the contender's Vite project

    Returns:
        whether the build succeeded, plus the output tail if it didn't
    """
    output = ""
    for cmd in (
        ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
        ["npm", "run", "build"],
    ):
        try:
            proc = subprocess.run(
                cmd, cwd=workspace, capture_output=True, text=True, timeout=BUILD_TIMEOUT_S
            )
        except subprocess.TimeoutExpired:
            return BuildResult(ok=False, log_tail=f"{' '.join(cmd)} timed out")
        output += proc.stdout + proc.stderr
        if proc.returncode != 0:
            return BuildResult(ok=False, log_tail=output[-BUILD_LOG_TAIL_CHARS:])
    return BuildResult(ok=True, log_tail="")


def init_workspace(workspace: Path) -> None:
    """Turns the seeded workspace into a git repo with a fixed identity.

    Args:
        workspace: the seeded folder the model builds in
    """
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


def screenshot(
    site_dir: Path,
    out_png: Path,
    settle_ms: int = SCREENSHOT_SETTLE_MS,
    hold: Sequence[tuple[str, int]] = (),
) -> ShotResult:
    """Serves a built site over HTTP and screenshots its game entry page.

    The page is served (not opened via file://) because ES module imports, which
    most three.js builds use, are blocked on file URLs. The site dir is served as
    the web root, matching Vite's default absolute asset paths (`/assets/...`).

    Args:
        site_dir: the build output folder (the workspace's `dist/`)
        out_png: where to write the 1280x720 screenshot
        settle_ms: wait after the network goes quiet, for the game to finish loading
        hold: keys to hold down in order after play starts, as (key, milliseconds),
            e.g. [("w", 2000)] to move forward for 2 s before the shot. Key names
            follow Playwright (`w`, `Shift`, `Space`, `ArrowUp`, ...).

    Returns:
        whether the entry exists, whether it loaded, and any console errors
    """
    if not (site_dir / GAME_ENTRY).exists():
        return ShotResult(has_entry=False, loaded=False, console_errors=[])

    # Port 0 lets the OS pick a free port, so both contenders can snapshot at once.
    handler = functools.partial(QuietHandler, directory=str(site_dir))
    server = AssetServer(("127.0.0.1", 0), handler)
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
            page.add_init_script(POINTER_LOCK_SHIM)
            page.on("console", on_console)
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                page.goto(url, wait_until="load", timeout=15_000)
                loaded = True
                # The game fetches its models (a 90 MB city, FBX animations, our
                # GLBs) after "load", so wait until the network goes quiet.
                with contextlib.suppress(PlaywrightTimeoutError):
                    page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
                # Models are parsed between downloads, so the network goes quiet
                # before the game is ready; the base game takes ~9 s headless.
                page.wait_for_timeout(settle_ms)
                # Click the middle like a player would, to get past a
                # "click to play" screen, then let a few frames of play render.
                page.mouse.click(640, 360)
                page.wait_for_timeout(AFTER_CLICK_MS)
                # Optional scripted input, so a shot can show the game in motion.
                for key, ms in hold:
                    page.keyboard.down(key)
                    page.wait_for_timeout(ms)
                    page.keyboard.up(key)
                out_png.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out_png))
            except Exception as exc:  # noqa: BLE001 - a broken build is data, not a harness crash
                errors.append(f"harness: {exc}")
            browser.close()
    finally:
        server.shutdown()

    return ShotResult(has_entry=True, loaded=loaded, console_errors=errors)


class AssetServer(ThreadingHTTPServer):
    """Local static server sized for games that request hundreds of files at once.

    The stdlib default listen backlog is 5, so a burst of asset requests gets
    connections reset (`net::ERR_CONNECTION_RESET` in the browser console).
    """

    request_queue_size = 256


class QuietHandler(SimpleHTTPRequestHandler):
    """Static file handler that doesn't spam the race console with access logs."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
        """Drops access log lines."""
