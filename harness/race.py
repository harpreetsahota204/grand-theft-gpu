"""CLI entry point: run every contender in parallel on one spec.

Normally invoked through the `buildoff` CLI (`harness.cli`), which adds a
confirmation guard for large budgets. Direct use:
    uv run python -m harness.race --spec prompts/game_spec.md --budget 100

Creates `<RUNS_ROOT>/<race_id>/`, optionally opens a viewer window per contender,
runs `harness.runner.ContenderRun` for each contender in its own thread, then
writes `summary.json`.

SIGINT (Ctrl-C) and SIGTERM abort the race cleanly: every running turn is
killed within a second and each contender ends with stop_reason "aborted".
`harness.pid` in the race folder lets `buildoff stop` do that from another
shell, and `stop_race` also kills any turn left running by a harness that
died without cleaning up (e.g. SIGKILL).

Nothing records the screen: the video is rendered later
from the timestamped turn logs, so nothing private ends up in footage.
"""

import argparse
import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from harness import fetch, sandbox, seed
from harness.config import REPO_ROOT, RaceConfig
from harness.runner import ABORT, ContenderRun, RunResult, kill_group

# Stop reasons that mean the run didn't finish the way a race should.
FAILED_STOPS: frozenset[str] = frozenset({"error", "leak", "meter_down", "aborted"})
# How long `stop_race` waits for the harness to shut down on its own.
STOP_GRACE_S: float = 60.0


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
    p.add_argument(
        "--pack",
        choices=["full", "primitives"],
        default="full",
        help="seeded assets: the full pack, or only the GPU (primitives race)",
    )
    p.add_argument(
        "--stop-on-done",
        action="store_true",
        help="end a run at the first DONE.md, after one review (smoke test)",
    )
    a = p.parse_args(argv)
    return RaceConfig(
        spec_path=a.spec.resolve(),
        budget_usd=a.budget,
        race_id=a.race_id or datetime.now().strftime("race-%Y%m%d-%H%M%S"),
        open_viewers=not a.no_viewers,
        pack=a.pack,
        stop_on_done=a.stop_on_done,
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


def keep_awake() -> None:
    """Keeps the Mac awake until this process exits, so a race can run unattended overnight.

    A sleeping Mac pauses every turn and drops API streams: the parallel $25 dry
    runs slept overnight and logged up to 32 API retries and 5 cut-off streams per
    turn, against none in a run on an awake machine. `caffeinate -w` exits on its
    own when the harness does. `-i` blocks idle sleep, `-s` system sleep on AC
    power, `-m` disk sleep; the display may still turn off. Closing the lid
    still sleeps the Mac unless an external display is attached.
    """
    with contextlib.suppress(OSError):
        subprocess.Popen(
            ["caffeinate", "-ims", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _abort(signum: int, _frame: object) -> None:
    """Signal handler: asks every contender to stop (see `runner.ABORT`)."""
    print(f"signal {signum}: aborting race, stopping running turns", flush=True)
    ABORT.set()


def main(argv: list[str]) -> list[RunResult]:
    """Runs the race end to end and prints a one-line result per contender.

    Returns:
        each contender's result
    """
    cfg = parse_args(argv)
    problem = sandbox.check()
    if problem:
        raise SystemExit(f"cannot isolate contenders: {problem}")
    cfg.race_dir.mkdir(parents=True, exist_ok=False)
    (cfg.race_dir / "config.json").write_text(
        json.dumps({**asdict(cfg), "spec_path": str(cfg.spec_path)}, indent=2)
    )
    pid_file = cfg.race_dir / "harness.pid"
    pid_file.write_text(str(os.getpid()))
    keep_awake()
    print(f"race dir: {cfg.race_dir}", flush=True)

    # Abort cleanly instead of dying with claude processes still running: they
    # run in their own sessions, so a signal to the harness never reaches them.
    ABORT.clear()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _abort)

    try:
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
    finally:
        pid_file.unlink(missing_ok=True)

    (cfg.race_dir / "summary.json").write_text(json.dumps([asdict(r) for r in results], indent=2))
    for r in results:
        print(
            f"{r.contender}: {r.stop_reason}, ${r.cost_usd:.2f}, {r.turns} turns, "
            f"first playable turn {r.first_playable_turn}, models {r.models_seen}"
        )
    return results


def failed(results: list[RunResult]) -> bool:
    """True if any contender ended on an error, leak, dead meter or abort."""
    return any(r.stop_reason in FAILED_STOPS for r in results)


def stop_race(race_dir: Path) -> dict[str, object]:
    """Stops a running race from outside: SIGTERM the harness, then clean up.

    The harness's own abort path kills each turn and writes result.json. If the
    harness is already dead (or doesn't exit within STOP_GRACE_S), any turn it
    left behind is killed through the process group in `logs/claude.pgid`.

    Args:
        race_dir: the race's folder

    Returns:
        what was stopped, JSON-ready
    """
    report: dict[str, object] = {"race_dir": str(race_dir), "harness": None}
    pid_file = race_dir / "harness.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text())
        # A harness killed with SIGKILL leaves a stale pid file, and the PID may
        # have been reused since; only signal it if it's still a harness.
        if _is_harness(pid):
            report["harness"] = pid
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + STOP_GRACE_S
            while time.monotonic() < deadline and pid_file.exists():
                time.sleep(1)
        pid_file.unlink(missing_ok=True)
    killed = []
    for pgid_file in sorted(race_dir.glob("*/logs/claude.pgid")):
        pgid = int(pgid_file.read_text())
        # Same PID-reuse guard: the group must still hold a claude process.
        if any("claude" in cmd for cmd in _group_commands(pgid)):
            kill_group(pgid)
            killed.append(pgid_file.parent.parent.name)
        pgid_file.unlink(missing_ok=True)
    report["turns_killed"] = killed
    return report


def _is_harness(pid: int) -> bool:
    """True if `pid` is a running race harness (`buildoff race|smoke` or `harness.race`)."""
    command = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True
    ).stdout
    return "buildoff" in command or "harness.race" in command


def _group_commands(pgid: int) -> list[str]:
    """Command lines of every process in a process group."""
    out = subprocess.run(
        ["ps", "-A", "-o", "pgid=,command="], capture_output=True, text=True
    ).stdout
    rows = (line.strip().split(None, 1) for line in out.splitlines() if line.strip())
    return [row[1] for row in rows if len(row) == 2 and row[0] == str(pgid)]


if __name__ == "__main__":
    main(sys.argv[1:])
