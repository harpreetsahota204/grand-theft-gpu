"""`buildoff`: the single command-line entry point for this repo.

Installed by `uv sync` (see `[project.scripts]` in pyproject.toml), so people
and agents run everything as `uv run buildoff <command>` instead of
remembering module paths:

    buildoff doctor                  check prerequisites
    buildoff fetch <id ...> [--tiers] | --core | --pattern G   download from the HF dataset
    buildoff status [race-id]        race progress as JSON (latest race by default)
    buildoff reviews [race-id]       every critic round as JSON
    buildoff play kimi|opus          open a contender's latest build in the browser
    buildoff stop [race-id]          abort a running race and kill its turns
    buildoff smoke                   ~$2-4 end-to-end check on the real setup
    buildoff race --budget 100 --yes the real race (spends real money)

Each subcommand is a thin wrapper: the work lives in `harness.doctor`,
`harness.fetch`, `harness.status` and `harness.race`. The code that builds the
asset dataset lives in the dataset itself, under build/.
"""

import argparse
import sys
from pathlib import Path

from harness import doctor, fetch, race
from harness.cliutil import CliError, JsonErrorParser, emit, fail
from harness.config import PROMPTS_DIR

# Races above this budget need --yes, so an agent (or a typo) can't start a
# $100-per-model run by accident. The smoke test runs at this cap, not above it.
CONFIRM_ABOVE_USD: float = 2.0
SMOKE_BUDGET_USD: float = 2.0
# The locked game spec each asset pack races on (see harness.fetch.PACK_PATTERNS).
SPEC_FOR_PACK: dict[str, str] = {"full": "game_spec.md", "primitives": "game_spec_primitives.md"}


def cmd_doctor(_: argparse.Namespace) -> int:
    """Checks prerequisites and returns the exit code."""
    return doctor.run_checks()


def cmd_fetch(args: argparse.Namespace) -> int:
    """Downloads assets at the pinned dataset revision; prints a JSON summary."""
    try:
        patterns = list(args.pattern or [])
        if args.ids:
            patterns += fetch.patterns_for_ids(args.ids, with_tiers=args.tiers)
        if args.core:
            patterns += fetch.CORE_PATTERNS
        if not patterns:
            raise CliError("nothing to fetch", "pass asset ids, --core, or --pattern", code=2)
    except KeyError as err:
        return fail(CliError(str(err).strip("'"), "find ids in assets/catalog.json"))
    except CliError as err:
        return fail(err)
    path = fetch.download(sorted(set(patterns)), args.out)
    # `.cache` is tested relative to the folder: the HF cache itself is under ~/.cache.
    files = [
        p for p in path.rglob("*") if p.is_file() and ".cache" not in p.relative_to(path).parts
    ]
    emit({"folder": str(path), "patterns": sorted(set(patterns)), "files": len(files)})
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Runs the cheap smoke race: both models add a floating GPU to the base game."""
    argv = [
        "--spec",
        str(PROMPTS_DIR / "smoke_spec.md"),
        "--budget",
        str(SMOKE_BUDGET_USD),
        "--stop-on-done",
    ]
    if not args.viewers:
        argv.append("--no-viewers")
    return 1 if race.failed(race.main(argv)) else 0


def cmd_race(args: argparse.Namespace) -> int:
    """Runs a race on the given spec, refusing large budgets without --yes."""
    if args.budget > CONFIRM_ABOVE_USD and not args.yes:
        print(
            f"Refusing: --budget {args.budget} spends up to ${args.budget:.2f} per model "
            f"(${args.budget * 2:.2f} total). Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 2
    # Each pack has its own locked spec: the primitives one lists no assets.
    spec = args.spec or PROMPTS_DIR / SPEC_FOR_PACK[args.pack]
    argv = ["--spec", str(spec), "--budget", str(args.budget), "--pack", args.pack]
    if args.race_id:
        argv += ["--race-id", args.race_id]
    if not args.viewers:
        argv.append("--no-viewers")
    return 1 if race.failed(race.main(argv)) else 0


def cmd_status(args: argparse.Namespace) -> int:
    """Prints a race's progress as JSON (the latest race by default)."""
    from harness import status

    try:
        emit(status.status(args.race_id))
    except CliError as err:
        return fail(err)
    return 0


def cmd_reviews(args: argparse.Namespace) -> int:
    """Prints every critic round of a race as JSON (the latest race by default)."""
    from harness import status

    try:
        emit(status.reviews(args.race_id))
    except CliError as err:
        return fail(err)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Aborts a running race (the latest by default) and kills any turn left running."""
    from harness import status

    try:
        emit(race.stop_race(status.race_dir(args.race_id)))
    except CliError as err:
        return fail(err)
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    """Serves a contender's latest build on localhost and opens it in the browser."""
    from harness import status

    try:
        status.play(args.race_id, args.contender, args.port, not args.no_open)
    except CliError as err:
        return fail(err)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Builds the `buildoff` argument parser with one subparser per command."""
    p = JsonErrorParser(prog="buildoff", description="The $100 GTA Build-Off harness.")
    sub = p.add_subparsers(dest="command", required=True, parser_class=JsonErrorParser)

    sub.add_parser("doctor", help="check prerequisites").set_defaults(func=cmd_doctor)

    s = sub.add_parser("smoke", help=f"cheap end-to-end check (${SMOKE_BUDGET_USD:.2f} per model)")
    s.add_argument("--viewers", action="store_true", help="open live viewer windows (macOS)")
    s.set_defaults(func=cmd_smoke)

    r = sub.add_parser("race", help="run a race (spends real money)")
    r.add_argument("--spec", type=Path, default=None, help="default: the pack's locked spec")
    r.add_argument(
        "--pack",
        choices=list(SPEC_FOR_PACK),
        default="full",
        help="full asset pack, or primitives (only the GPU; models build the rest)",
    )
    r.add_argument("--budget", type=float, default=100.0, help="USD cap per model")
    r.add_argument("--race-id", default=None, help="output folder name (default: timestamp)")
    r.add_argument("--viewers", action="store_true", help="open live viewer windows (macOS)")
    r.add_argument("--yes", action="store_true", help=f"confirm budgets above ${CONFIRM_ABOVE_USD}")
    r.set_defaults(func=cmd_race)

    st = sub.add_parser(
        "status",
        help="race progress as JSON (free, read-only)",
        description=(
            "Summarise a race from its log files: turns, spend, critic tiers, stop reason, "
            "the Nexus session to watch, and the latest screenshot. Works during and after a race."
        ),
    )
    st.add_argument("race_id", nargs="?", default=None, help="default: the latest race")
    st.set_defaults(func=cmd_status)

    rv = sub.add_parser(
        "reviews",
        help="every critic round as JSON (free, read-only)",
        description=(
            "Trace the critic over a race: per contender and round, the tier, the Tier 4 "
            "claim and checks, that review's cost and time, its notes, and its screenshots."
        ),
    )
    rv.add_argument("race_id", nargs="?", default=None, help="default: the latest race")
    rv.set_defaults(func=cmd_reviews)

    sp = sub.add_parser(
        "stop",
        help="abort a running race and kill its turns",
        description=(
            "Send the race harness SIGTERM (each contender stops as 'aborted' and writes "
            "result.json), then kill any claude turn still running, e.g. after the harness "
            "itself was killed."
        ),
    )
    sp.add_argument("race_id", nargs="?", default=None, help="default: the latest race")
    sp.set_defaults(func=cmd_stop)

    pl = sub.add_parser(
        "play",
        help="open a contender's latest build in your browser",
        description="Serve <contender>'s latest build (workspace/dist) on localhost; Ctrl-C stops.",
    )
    pl.add_argument("contender", help="kimi or opus")
    pl.add_argument("--race-id", default=None, help="default: the latest race")
    pl.add_argument("--port", type=int, default=0, help="default: any free port")
    pl.add_argument("--no-open", action="store_true", help="print the URL, don't open a browser")
    pl.set_defaults(func=cmd_play)

    f = sub.add_parser(
        "fetch",
        help="download assets from the HF dataset (pinned revision)",
        description=(
            "Download assets from the Hugging Face dataset at the pinned revision. "
            "Pass catalog ids (from assets/catalog.json), --core for the seeded set, or "
            "--pattern for dataset globs. Prints a JSON summary."
        ),
    )
    f.add_argument("ids", nargs="*", help="catalog ids, e.g. rocketbox-avatars/chef-female-01")
    f.add_argument("--core", action="store_true", help="the seeded set (~650 MB)")
    f.add_argument("--pattern", action="append", help="dataset glob, e.g. 'meta-mhr/*'")
    f.add_argument("--tiers", action="store_true", help="include people's lods/mobile/collision")
    f.add_argument("--out", type=Path, default=None, help="folder (default: HF cache)")
    f.set_defaults(func=cmd_fetch)
    return p


def main() -> None:
    """Entry point for the `buildoff` console script."""
    args = build_parser().parse_args()
    sys.exit(args.func(args))
