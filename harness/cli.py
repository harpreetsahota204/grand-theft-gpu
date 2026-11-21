"""`buildoff`: the single command-line entry point for this repo.

Installed by `uv sync` (see `[project.scripts]` in pyproject.toml), so people
and agents run everything as `uv run buildoff <command>` instead of
remembering module paths:

    buildoff doctor                  check prerequisites
    buildoff assets [gpu|cars|props|all] [--out DIR]   rebuild assets/ from source
    buildoff smoke                   ~$0.30 end-to-end check on the real setup
    buildoff race --budget 100 --yes the real race (spends real money)

Each subcommand is a thin wrapper: the work lives in `harness.doctor`,
`harness.assets` and `harness.race`.
"""

import argparse
import sys
from pathlib import Path

from harness import doctor, race
from harness.config import ASSETS_DIR, PROMPTS_DIR

# Races above this budget need --yes, so an agent (or a typo) can't start a
# $100-per-model run by accident. The smoke test stays under it.
CONFIRM_ABOVE_USD: float = 2.0
SMOKE_BUDGET_USD: float = 0.5


def cmd_doctor(_: argparse.Namespace) -> int:
    """Checks prerequisites and returns the exit code."""
    return doctor.run_checks()


def cmd_assets(args: argparse.Namespace) -> int:
    """Rebuilds the requested asset set from its original sources."""
    # Lazy import: huggingface_hub is only needed here.
    from harness import assets

    assets.build(args.what, args.out)
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Runs the cheap smoke race: both models add a floating GPU to the base game."""
    argv = ["--spec", str(PROMPTS_DIR / "smoke_spec.md"), "--budget", str(SMOKE_BUDGET_USD)]
    if not args.viewers:
        argv.append("--no-viewers")
    race.main(argv)
    return 0


def cmd_race(args: argparse.Namespace) -> int:
    """Runs a race on the given spec, refusing large budgets without --yes."""
    if args.budget > CONFIRM_ABOVE_USD and not args.yes:
        print(
            f"Refusing: --budget {args.budget} spends up to ${args.budget:.2f} per model "
            f"(${args.budget * 2:.2f} total). Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 2
    argv = ["--spec", str(args.spec), "--budget", str(args.budget)]
    if args.race_id:
        argv += ["--race-id", args.race_id]
    if args.no_viewers:
        argv.append("--no-viewers")
    race.main(argv)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds the `buildoff` argument parser with one subparser per command."""
    p = argparse.ArgumentParser(prog="buildoff", description="The $100 GTA Build-Off harness.")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check prerequisites").set_defaults(func=cmd_doctor)

    a = sub.add_parser("assets", help="rebuild assets/ from original sources")
    a.add_argument("what", nargs="?", default="all", choices=["gpu", "cars", "props", "all"])
    a.add_argument("--out", type=Path, default=ASSETS_DIR, help="assets root (default: assets/)")
    a.set_defaults(func=cmd_assets)

    s = sub.add_parser("smoke", help=f"cheap end-to-end check (${SMOKE_BUDGET_USD:.2f} per model)")
    s.add_argument("--viewers", action="store_true", help="open live viewer windows (macOS)")
    s.set_defaults(func=cmd_smoke)

    r = sub.add_parser("race", help="run a race (spends real money)")
    r.add_argument("--spec", type=Path, default=PROMPTS_DIR / "game_spec.md")
    r.add_argument("--budget", type=float, default=100.0, help="USD cap per model")
    r.add_argument("--race-id", default=None, help="output folder name (default: timestamp)")
    r.add_argument("--no-viewers", action="store_true", help="skip live viewer windows")
    r.add_argument("--yes", action="store_true", help=f"confirm budgets above ${CONFIRM_ABOVE_USD}")
    r.set_defaults(func=cmd_race)
    return p


def main() -> None:
    """Entry point for the `buildoff` console script."""
    args = build_parser().parse_args()
    sys.exit(args.func(args))
