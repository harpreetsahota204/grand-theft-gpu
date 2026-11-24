"""Screenshot tool for racing models: build the game, render it, report as JSON.

Models write three.js code but can't otherwise see the result. Each race
workspace gets a `tools/screenshot` wrapper (written by `harness.seed`) that runs
this module, so a model can look at its own game with Claude Code's Read tool
and fix what's wrong. Both contenders' models were verified to read images.

It renders exactly the way the harness's per-turn evidence does
(`harness.snapshot`): Vite build, local static server, headless Chromium with
the pointer-lock shim, a click to start play, optional scripted input, then a
1280x720 PNG.

Usage (from inside a workspace, via the wrapper):
    tools/screenshot                          # build + shot -> tools/shots/latest.png
    tools/screenshot --hold w:2000            # hold W for 2 s first (walk/drive forward)
    tools/screenshot --hold w+d:1500          # hold W and D together (drive and steer)
    tools/screenshot --hold e:200 --shot talk --hold w:3000 --out tools/shots/after.png
    tools/screenshot --look 300,0 --click 640,360 --wait 1000
    tools/screenshot --no-build               # reuse the last dist/ build
    tools/screenshot --help

Input flags run in the order given, all in one play session, so one call can
play a whole sequence and save shots along the way (`--shot NAME`).

Usage errors are JSON on stderr with exit code 2 (see `harness.cliutil`).
Output: one JSON object on stdout:
    {"ok", "png", "shots", "build_ok", "loaded", "page_errors", "console_errors",
     "build_log_tail"}
`ok` is true only if the build succeeded, the page loaded and a new PNG was written.
Exit code 0 when ok, 1 otherwise. Non-interactive and safe to run repeatedly.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from harness.cliutil import JsonErrorParser
from harness.config import BUILD_DIR
from harness.snapshot import Step, build, screenshot

# Shorter than the harness's per-turn settle: a model iterating on visuals wants
# fast feedback, and can pass --settle-ms for a slow-loading scene.
DEFAULT_SETTLE_MS: int = 8000
MAX_ERRORS: int = 10


# Playwright's named keys are case-sensitive ("Space", not "space"), and a
# smoke-test critic lost a call to that. Named keys are matched case-insensitively;
# single characters pass through unchanged, since "W" and "w" differ.
NAMED_KEYS: dict[str, str] = {
    name.lower(): name
    for name in (
        "Space",
        "Enter",
        "Escape",
        "Tab",
        "Backspace",
        "Delete",
        "Shift",
        "Control",
        "Alt",
        "Meta",
        "CapsLock",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Insert",
        *(f"F{i}" for i in range(1, 13)),
    )
} | {
    "esc": "Escape",
    "ctrl": "Control",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "return": "Enter",
}

# --shot names become files in tools/shots/, so keep them to safe file names.
SHOT_NAME: re.Pattern[str] = re.compile(r"[A-Za-z0-9_-]{1,64}")


def parse_hold(spec: str) -> Step:
    """Parses one `KEY[+KEY...]:MS` hold spec, e.g. "w:2000", "w+d:1500" or "ArrowUp:500".

    Raises:
        argparse.ArgumentTypeError: if the spec isn't KEYS:MS with a positive MS
    """
    key, sep, ms = spec.rpartition(":")
    if not sep or not key or not ms.isdigit() or int(ms) <= 0:
        raise argparse.ArgumentTypeError(f"expected KEY:MS like w:2000, got {spec!r}")
    keys = key.split("+")
    # "+" on its own (or "a++") names the plus key, not a chord.
    if not all(keys):
        keys = [key]
    return Step("keys", keys=tuple(NAMED_KEYS.get(k.lower(), k) for k in keys), ms=int(ms))


def parse_wait(spec: str) -> Step:
    """Parses `--wait MS`: let the game run with no input."""
    if not spec.isdigit() or int(spec) <= 0:
        raise argparse.ArgumentTypeError(f"expected milliseconds like 1000, got {spec!r}")
    return Step("wait", ms=int(spec))


def parse_shot(spec: str) -> Step:
    """Parses `--shot NAME`: save tools/shots/NAME.png at this point in the sequence."""
    if not SHOT_NAME.fullmatch(spec):
        raise argparse.ArgumentTypeError(f"expected a name like after-steal, got {spec!r}")
    # Relative for now; run() resolves it against the workspace.
    return Step("shot", path=Path("tools") / "shots" / f"{spec}.png")


def _parse_pair(spec: str, example: str) -> tuple[int, int]:
    """Parses "A,B" into two ints (negative allowed)."""
    parts = spec.split(",")
    try:
        a, b = (int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected two numbers like {example}, got {spec!r}"
        ) from None
    return a, b


def parse_click(spec: str) -> Step:
    """Parses `--click X,Y`: a left click at viewport pixel X,Y (1280x720)."""
    x, y = _parse_pair(spec, "640,360")
    return Step("click", x=x, y=y)


def parse_look(spec: str) -> Step:
    """Parses `--look DX,DY`: mouse movement, as a pointer-locked camera sees it."""
    dx, dy = _parse_pair(spec, "300,0")
    return Step("look", x=dx, y=dy)


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser (shown by `tools/screenshot --help`)."""
    p = JsonErrorParser(
        prog="tools/screenshot",
        description=(
            "Build the game and save a gameplay screenshot you can open with the Read "
            "tool. Prints JSON; exit 0 if a screenshot was written. The input flags "
            "(--hold, --wait, --shot, --click, --look) run in the order given, in one "
            "play session, before the final shot."
        ),
    )
    p.add_argument("workspace", type=Path, help="the game folder (set by the wrapper)")
    p.add_argument(
        "--out", type=Path, default=None, help="final PNG path (default: tools/shots/latest.png)"
    )
    # Every input flag appends to one list, so their order on the command line is
    # the order they're played in.
    for flag, parse, metavar, text in (
        (
            "--hold",
            parse_hold,
            "KEYS:MS",
            "hold keys, e.g. w:2000, space:100, or several at once: w+d:1500",
        ),
        ("--wait", parse_wait, "MS", "let the game run with no input, e.g. 1000"),
        ("--shot", parse_shot, "NAME", "save tools/shots/NAME.png at this point"),
        ("--click", parse_click, "X,Y", "left click at a viewport pixel (1280x720)"),
        ("--look", parse_look, "DX,DY", "move the mouse/camera by DX,DY, e.g. 300,0"),
    ):
        p.add_argument(
            flag, dest="steps", type=parse, action="append", default=[], metavar=metavar, help=text
        )
    p.add_argument(
        "--settle-ms", type=int, default=DEFAULT_SETTLE_MS, help="wait for the scene to load"
    )
    p.add_argument("--no-build", action="store_true", help="skip `npm run build`, reuse dist/")
    return p


def run(args: argparse.Namespace) -> dict[str, object]:
    """Builds (unless --no-build) and screenshots the workspace's game.

    Returns:
        the JSON-ready result dict
    """
    workspace = args.workspace.resolve()
    out = (args.out or workspace / "tools" / "shots" / "latest.png").resolve()
    steps = [
        Step("shot", path=workspace / st.path) if st.kind == "shot" and st.path else st
        for st in args.steps
    ]
    extra = [st.path for st in steps if st.kind == "shot" and st.path]
    # Remove previous shots first, so a failed render can't report a stale PNG.
    for path in (out, *extra):
        path.unlink(missing_ok=True)
    built_ok, log_tail = True, ""
    if not args.no_build:
        result = build(workspace)
        built_ok, log_tail = result.ok, result.log_tail
    if not built_ok:
        return {
            "ok": False,
            "png": None,
            "shots": [],
            "build_ok": False,
            "loaded": False,
            "page_errors": [],
            "console_errors": [],
            "build_log_tail": log_tail,
        }
    shot = screenshot(workspace / BUILD_DIR, out, settle_ms=args.settle_ms, steps=steps)
    return {
        "ok": shot.shot_written,
        "png": str(out) if shot.shot_written else None,
        "shots": [str(path) for path in extra if path.exists()],
        "build_ok": True,
        "loaded": shot.loaded,
        "page_errors": shot.page_errors[:MAX_ERRORS],
        "console_errors": shot.console_errors[:MAX_ERRORS],
        "build_log_tail": "",
    }


def main() -> None:
    """CLI entry point: prints the result JSON and exits 0 if a PNG was written."""
    result = run(build_parser().parse_args())
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
