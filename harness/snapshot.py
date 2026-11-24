"""Per-turn evidence: a git commit, a Vite build, and a screenshot of the game.

`harness.runner` calls `commit`, `build` and `screenshot` after every turn. The
commits (in a history repo outside the workspace, see `init_history`) give a
timeline to score against the tier checklist; the build tells us
whether the game still compiles; the screenshots give footage for the video and
tell us when the first playable build appeared.
"""

import contextlib
import functools
import subprocess
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal

from playwright.sync_api import ConsoleMessage, Page, sync_playwright
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

# Mouse-look: games behind pointer lock read `movementX/Y`, which a real cursor
# can't supply past the viewport edge. So a look is a burst of synthetic
# mousemove events on the locked element (or the page), split into this many
# frames so per-frame camera code sees a smooth turn.
LOOK_STEPS: int = 10
LOOK_STEP_MS: int = 16
LOOK_JS: str = """
([dx, dy]) => {
  const target = document.pointerLockElement || document.elementFromPoint(640, 360) || document;
  target.dispatchEvent(new MouseEvent("mousemove", {
    bubbles: true, movementX: dx, movementY: dy, clientX: 640, clientY: 360,
  }));
}
"""


@dataclass(frozen=True)
class Step:
    """One scripted input step, run in order after play starts.

    Attributes:
        kind: "keys" (hold `keys` together for `ms`), "wait" (`ms`), "shot"
            (save the page to `path` now), "click" (at `x`, `y`) or "look"
            (turn the camera by `x`, `y` pixels of mouse movement)
        keys: Playwright key names held together, e.g. ("w", "d") to drive and steer
        ms: how long to hold the keys, or to wait
        x: click x, or look dx
        y: click y, or look dy
        path: where a "shot" step writes its PNG
    """

    kind: Literal["keys", "wait", "shot", "click", "look"]
    keys: tuple[str, ...] = ()
    ms: int = 0
    x: int = 0
    y: int = 0
    path: Path | None = None


@dataclass(frozen=True)
class ShotResult:
    """Outcome of screenshotting the game after a turn.

    Attributes:
        has_entry: whether the built site has the game entry file
        loaded: whether the page's load event fired
        shot_written: whether the PNG was saved
        page_errors: uncaught exceptions thrown by the game, plus harness-side
            failures (navigation or screenshot timeouts), prefixed "harness:"
        console_errors: `console.error` messages, including failed resource
            loads; recorded as evidence but they don't make a turn unplayable
    """

    has_entry: bool
    loaded: bool
    shot_written: bool = False
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)

    @property
    def playable(self) -> bool:
        """Loaded and rendered with no uncaught exception.

        Console errors alone don't count: a missing favicon or a logged warning
        shouldn't mark a working game broken.
        """
        return self.loaded and self.shot_written and not self.page_errors


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


# Paths left out of the per-turn history whatever the workspace's .gitignore says:
# installed packages, build output and the model's scratch screenshots.
EVIDENCE_EXCLUDES: tuple[str, ...] = (
    ":(exclude,glob)**/node_modules/**",
    ":(exclude,glob)dist/**",
    ":(exclude,glob)tools/shots/**",
)


def _git(history: Path, workspace: Path, *args: str) -> str:
    """Runs git on the evidence history for a workspace and returns stdout."""
    proc = subprocess.run(
        ["git", f"--git-dir={history}", f"--work-tree={workspace}", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def init_history(history: Path) -> None:
    """Creates the evidence history: a git repo kept outside the workspace.

    The model can't see or rewrite it (its sandbox can't read outside the
    workspace), so commit N is always what the workspace held after turn N. A
    model that wants git for itself can `git init` in its workspace; the
    history ignores that nested `.git`.

    Args:
        history: the bare-style git dir to create, e.g. `<contender>/history.git`
    """
    # Bare, so git never creates a working tree next to it; core.bare=false then
    # lets every command pair it with the workspace via --work-tree.
    subprocess.run(["git", "init", "-q", "--bare", str(history)], check=True)
    # A local identity so commits never depend on (or leak) the user's git config.
    for key, value in (
        ("user.name", "evidence-harness"),
        ("user.email", "harness@localhost"),
        ("core.bare", "false"),
    ):
        subprocess.run(["git", f"--git-dir={history}", "config", key, value], check=True)


def commit(history: Path, workspace: Path, message: str) -> str:
    """Commits everything in the workspace to the evidence history, even if nothing changed.

    `-f` adds files the model's own .gitignore would hide, so the history
    records the whole game; `EVIDENCE_EXCLUDES` keeps out what shouldn't be in it.

    Args:
        history: the evidence git dir (see `init_history`)
        workspace: the contender's game folder
        message: commit message, e.g. "turn 3"

    Returns:
        the new commit's SHA
    """
    _git(history, workspace, "add", "-A", "-f", "--", ".", *EVIDENCE_EXCLUDES)
    # --allow-empty keeps one commit per turn so turn N always maps to commit N.
    _git(history, workspace, "commit", "-q", "--allow-empty", "--no-verify", "-m", message)
    return _git(history, workspace, "rev-parse", "HEAD").strip()


def screenshot(
    site_dir: Path,
    out_png: Path,
    settle_ms: int = SCREENSHOT_SETTLE_MS,
    steps: Sequence[Step] = (),
    later: Sequence[tuple[int, Path]] = (),
) -> ShotResult:
    """Serves a built site over HTTP and screenshots its game entry page.

    The page is served (not opened via file://) because ES module imports, which
    most three.js builds use, are blocked on file URLs. The site dir is served as
    the web root, matching Vite's default absolute asset paths (`/assets/...`).

    Args:
        site_dir: the build output folder (the workspace's `dist/`)
        out_png: where to write the 1280x720 screenshot
        settle_ms: wait after the network goes quiet, for the game to finish loading
        steps: scripted input after play starts, run in order before the main
            shot (see `Step`), e.g. hold W and D together to drive and steer, or
            save in-between shots. Key names follow Playwright (`w`, `Shift`,
            `Space`, `ArrowUp`, ...).
        later: extra shots of the same page after the main one, as (wait ms,
            path), with no input in between; `harness.checks` compares them to
            see whether the world moves on its own.

    Returns:
        whether the entry exists, loaded and was captured, plus any errors
    """
    if not (site_dir / GAME_ENTRY).exists():
        return ShotResult(has_entry=False, loaded=False)

    # Port 0 lets the OS pick a free port, so both contenders can snapshot at once.
    handler = functools.partial(QuietHandler, directory=str(site_dir))
    server = AssetServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/{GAME_ENTRY}"

    console_errors: list[str] = []
    page_errors: list[str] = []
    loaded = written = False

    def on_console(msg: ConsoleMessage) -> None:
        """Keeps console errors; drops log/info/warning noise."""
        if msg.type == "error":
            console_errors.append(msg.text)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=CHROMIUM_ARGS)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.add_init_script(POINTER_LOCK_SHIM)
            page.on("console", on_console)
            page.on("pageerror", lambda e: page_errors.append(str(e)))
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
                for step in steps:
                    _run_step(page, step)
                out_png.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out_png))
                for wait_ms, path in later:
                    page.wait_for_timeout(wait_ms)
                    page.screenshot(path=str(path))
                written = True
            except Exception as exc:  # noqa: BLE001 - a broken build is data, not a harness crash
                page_errors.append(f"harness: {exc}")
            finally:
                browser.close()
    finally:
        server.shutdown()
        # shutdown() only stops the loop; close the listening socket too, or
        # every turn leaks one.
        server.server_close()

    return ShotResult(
        has_entry=True,
        loaded=loaded,
        shot_written=written,
        page_errors=page_errors,
        console_errors=console_errors,
    )


def _run_step(page: Page, step: Step) -> None:
    """Plays one scripted input step on the page (see `Step`)."""
    if step.kind == "keys":
        for key in step.keys:
            page.keyboard.down(key)
        page.wait_for_timeout(step.ms)
        # Release in reverse, like fingers coming off a chord.
        for key in reversed(step.keys):
            page.keyboard.up(key)
    elif step.kind == "wait":
        page.wait_for_timeout(step.ms)
    elif step.kind == "shot" and step.path is not None:
        step.path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(step.path))
    elif step.kind == "click":
        page.mouse.click(step.x, step.y)
    elif step.kind == "look":
        for _ in range(LOOK_STEPS):
            page.evaluate(LOOK_JS, [step.x / LOOK_STEPS, step.y / LOOK_STEPS])
            page.wait_for_timeout(LOOK_STEP_MS)


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
