"""CLI entry point: run every contender in parallel on one spec.

Normally invoked through the `buildoff` CLI (`harness.cli`), which adds a
confirmation guard for large budgets. Direct use:
    uv run python -m harness.race --spec prompts/game_spec.md --budget 100

Creates `<RUNS_ROOT>/<race_id>/`, optionally opens a viewer window per contender,
runs `harness.runner.ContenderRun` for each contender in its own thread, then
writes `summary.json`. Nothing records the screen: the video is rendered later
from the timestamped turn logs, so nothing private ends up in footage.
"""

import argparse
import json
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from harness import fetch, seed
from harness.config import REPO_ROOT, RaceConfig
from harness.runner import ContenderRun, RunResult


def parse_args(argv: list[str]) -> RaceConfig:
    """Turns CLI flags into a RaceConfig.

    Args:
        argv: command-line arguments without the program name

    Returns:
        the race configuration
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--spec", type=Path, required=True, help="game spec markdown file")
    p.add_argument("--budget", type=float, default=100.0, help="USD cap per contender")
    p.add_argument("--race-id", default=None, help="output folder name (default: timestamp)")
    p.add_argument("--no-viewers", action="store_true", help="skip opening viewer windows")
    a = p.parse_args(argv)
    return RaceConfig(
        spec_path=a.spec.resolve(),
        budget_usd=a.budget,
        race_id=a.race_id or datetime.now().strftime("race-%Y%m%d-%H%M%S"),
        open_viewers=not a.no_viewers,
    )


def open_viewer(contender_dir: Path) -> None:
    """Opens a macOS Terminal window running the live viewer for one contender.

    Args:
        contender_dir: `<race_dir>/<contender>`
    """
    cmd = (
        f"cd {shlex.quote(str(REPO_ROOT))} && "
        f"uv run python -m harness.viewer {shlex.quote(str(contender_dir))}"
    )
    # AppleScript string literal: escape backslashes and quotes from the shell command.
    escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'tell application "Terminal" to do script "{escaped}"'],
        check=True,
    )


def main(argv: list[str]) -> None:
    """Runs the race end to end and prints a one-line result per contender."""
    cfg = parse_args(argv)
    cfg.race_dir.mkdir(parents=True, exist_ok=False)
    (cfg.race_dir / "config.json").write_text(
        json.dumps({**asdict(cfg), "spec_path": str(cfg.spec_path)}, indent=2)
    )
    print(f"race dir: {cfg.race_dir}", flush=True)

    # Fetch the pinned base game once, before the contender threads start, so
    # they don't both try to populate the cache at the same time.
    seed.base_cache()
    # Same for the core assets: download once into the HF cache up front.
    fetch.core()

    runs = [ContenderRun(c, cfg) for c in cfg.contenders]
    if cfg.open_viewers:
        for run in runs:
            open_viewer(run.root)

    # One thread per contender: each spends nearly all its time waiting on its
    # claude subprocess, so threads give true parallelism here.
    with ThreadPoolExecutor(max_workers=len(runs)) as pool:
        results: list[RunResult] = list(pool.map(lambda r: r.run(), runs))

    (cfg.race_dir / "summary.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    for r in results:
        print(
            f"{r.contender}: {r.stop_reason}, ${r.cost_usd:.2f}, {r.turns} turns, "
            f"first playable turn {r.first_playable_turn}, models {r.models_seen}"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
