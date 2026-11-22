"""Screenshot tool for racing models: build the game, render it, report as JSON.

Models write three.js code but can't otherwise see the result. Each race
workspace gets a `tools/screenshot` wrapper (written by `harness.seed`) that runs
this module, so a model can look at its own game with Claude Code's Read tool
and fix what's wrong. Both contenders' models were verified to read images.

It renders exactly the way the harness's per-turn evidence does
(`harness.snapshot`): Vite build, local static server, headless Chromium with
the pointer-lock shim, a click to start play, optional held keys, then a
1280x720 PNG.

Usage (from inside a workspace, via the wrapper):
    tools/screenshot                          # build + shot -> tools/shots/latest.png
    tools/screenshot --hold w:2000            # hold W for 2 s first (walk/drive forward)
    tools/screenshot --hold w:1500 --hold a:500 --out tools/shots/turning.png
    tools/screenshot --no-build               # reuse the last dist/ build
    tools/screenshot --help

Usage errors are JSON on stderr with exit code 2 (see `harness.cliutil`).
Output: one JSON object on stdout:
    {"ok", "png", "build_ok", "loaded", "page_errors", "console_errors", "build_log_tail"}
`ok` is true only if the build succeeded, the page loaded and a new PNG was written.
Exit code 0 when ok, 1 otherwise. Non-interactive and safe to run repeatedly.
"""

import argparse
import json
import sys
from pathlib import Path

from harness.cliutil import JsonErrorParser
from harness.config import BUILD_DIR
from harness.snapshot import build, screenshot

# Shorter than the harness's per-turn settle: a model iterating on visuals wants
# fast feedback, and can pass --settle-ms for a slow-loading scene.
DEFAULT_SETTLE_MS: int = 8000
MAX_ERRORS: int = 10


def parse_hold(spec: str) -> tuple[str, int]:
    """Parses one `KEY:MS` hold spec, e.g. "w:2000" or "ArrowUp:500".

    Raises:
        argparse.ArgumentTypeError: if the spec isn't KEY:MS with a positive MS
    """
    key, sep, ms = spec.rpartition(":")
    if not sep or not key or not ms.isdigit() or int(ms) <= 0:
        raise argparse.ArgumentTypeError(f"expected KEY:MS like w:2000, got {spec!r}")
    return key, int(ms)


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI parser (shown by `tools/screenshot --help`)."""
    p = JsonErrorParser(
        prog="tools/screenshot",
        description=(
            "Build the game and save a gameplay screenshot you can open with the Read "
            "tool. Prints JSON; exit 0 if a screenshot was written."
        ),
    )
    p.add_argument("workspace", type=Path, help="the game folder (set by the wrapper)")
    p.add_argument(
        "--out", type=Path, default=None, help="PNG path (default: tools/shots/latest.png)"
    )
    p.add_argument(
        "--hold",
        type=parse_hold,
        action="append",
        default=[],
        metavar="KEY:MS",
        help="hold a key after play starts, e.g. w:2000 (repeatable, applied in order)",
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
    # Remove the previous shot first, so a failed render can't report a stale PNG.
    out.unlink(missing_ok=True)
    built_ok, log_tail = True, ""
    if not args.no_build:
        result = build(workspace)
        built_ok, log_tail = result.ok, result.log_tail
    if not built_ok:
        return {
            "ok": False,
            "png": None,
            "build_ok": False,
            "loaded": False,
            "page_errors": [],
            "console_errors": [],
            "build_log_tail": log_tail,
        }
    shot = screenshot(workspace / BUILD_DIR, out, settle_ms=args.settle_ms, hold=args.hold)
    return {
        "ok": shot.shot_written,
        "png": str(out) if shot.shot_written else None,
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
