"""`buildoff`: the single command-line entry point for this repo.

Installed by `uv sync` (see `[project.scripts]` in pyproject.toml), so people
and agents run everything as `uv run buildoff <command>` instead of
remembering module paths:

    buildoff doctor                  check prerequisites
    buildoff assets [gpu|cars|props|catalog|all] [--out DIR]   rebuild assets/ from source
    buildoff inventory search police car   find assets (JSON out; see `inventory schema`)
    buildoff fetch <id ...> [--tiers] | --core | --pattern G   download from the HF dataset
    buildoff smoke                   ~$0.30 end-to-end check on the real setup
    buildoff race --budget 100 --yes the real race (spends real money)

Each subcommand is a thin wrapper: the work lives in `harness.doctor`,
`harness.assets`, `harness.catalog`, `harness.inventory` and `harness.race`.
"""

import argparse
import sys
from pathlib import Path

from harness import doctor, inventory, race
from harness.cliutil import JsonErrorParser
from harness.config import ASSETS_DIR, MIRROR_DIR, PROMPTS_DIR

# Races above this budget need --yes, so an agent (or a typo) can't start a
# $100-per-model run by accident. The smoke test stays under it.
CONFIRM_ABOVE_USD: float = 2.0
SMOKE_BUDGET_USD: float = 0.5


def cmd_doctor(_: argparse.Namespace) -> int:
    """Checks prerequisites and returns the exit code."""
    return doctor.run_checks()


def cmd_assets(args: argparse.Namespace) -> int:
    """Rebuilds the requested asset set from source, then refreshes the catalog."""
    # Lazy imports: huggingface_hub and trimesh are only needed here.
    from harness import assets, catalog, dataset, mirror, sfcity

    staging = args.out if args.out != ASSETS_DIR else MIRROR_DIR
    if args.what == "city":
        sfcity.build(staging)
        return 0
    if args.what == "dataset":
        dataset.build(staging)
        return 0
    if args.what == "publish":
        print(dataset.publish(staging))
        return 0
    if args.what == "mirror":
        # Third-party sets go to a staging folder (the local copy of the HF dataset),
        # never into the repo's assets/.
        mirror.mirror(staging, args.source)
        return 0
    if args.what != "catalog":
        assets.build(args.what, args.out)
    # The catalog describes this repo's assets/, so only refresh it when that
    # is what was rebuilt (not when rebuilding into a scratch --out to diff).
    if args.what in ("catalog", "all") and args.out == ASSETS_DIR:
        print(f"catalog: {catalog.write_catalog()} assets -> {catalog.CATALOG_PATH}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Downloads assets at the pinned dataset revision; prints a JSON summary."""
    from harness import fetch

    try:
        patterns = list(args.pattern or [])
        if args.ids:
            patterns += fetch.patterns_for_ids(args.ids, with_tiers=args.tiers)
        if args.core:
            patterns += fetch.CORE_PATTERNS
        if not patterns:
            raise inventory.InventoryError(
                "nothing to fetch", "pass asset ids, --core, or --pattern", code=2
            )
    except KeyError as err:
        return inventory.fail(
            inventory.InventoryError(str(err).strip("'"), "find ids with `inventory search`")
        )
    except inventory.InventoryError as err:
        return inventory.fail(err)
    path = fetch.download(sorted(set(patterns)), args.out)
    # `.cache` is tested relative to the folder: the HF cache itself is under ~/.cache.
    files = [
        p for p in path.rglob("*") if p.is_file() and ".cache" not in p.relative_to(path).parts
    ]
    inventory.emit(
        {"folder": str(path), "patterns": sorted(set(patterns)), "files": len(files)}, "json"
    )
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    """Runs one inventory query and prints JSON; errors go to stderr as JSON."""
    if args.action == "schema":
        inventory.emit(inventory.SCHEMA, "json")
        return 0
    try:
        assets = inventory.load()
        if args.action == "categories":
            result = inventory.categories(assets)
        elif args.action == "show":
            result = inventory.show(assets, args.ids)
        else:
            pool = inventory.filter_assets(assets, args.category, args.kind, args.tag)
            rows = inventory.search(pool, args.query) if args.action == "search" else pool
            rows = rows[: args.limit] if args.limit else rows
            result = [inventory.summarize(r, args.full) for r in rows]
    except inventory.InventoryError as err:
        return inventory.fail(err)
    inventory.emit(result, args.format)
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


def add_inventory(sub: "argparse._SubParsersAction[JsonErrorParser]") -> None:
    """Adds `inventory` and its actions (categories, list, search, show, schema)."""
    inv = sub.add_parser(
        "inventory",
        help="search the asset catalog (JSON out)",
        description=(
            "Query the 3D asset catalog. Non-interactive and deterministic; prints JSON "
            "to stdout and JSON errors to stderr. Start with `schema` or `categories`."
        ),
    )
    acts = inv.add_subparsers(dest="action", required=True)

    def common(p: argparse.ArgumentParser, filters: bool) -> None:
        """Adds output-format flags, plus filters for list/search."""
        p.add_argument("--format", choices=["json", "jsonl"], default="json")
        if filters:
            p.add_argument("--category", help="exact category, e.g. vehicle, prop, loot")
            p.add_argument("--kind", help="exact kind, e.g. vehicle, vehicle-part")
            p.add_argument("--tag", help="exact tag, e.g. heist-target, articulated")
            p.add_argument("--limit", type=int, default=0, help="max results (0 = all)")
            p.add_argument("--full", action="store_true", help="full records, not summaries")

    common(acts.add_parser("categories", help="asset counts per category and kind"), False)
    common(acts.add_parser("list", help="all assets, optionally filtered"), True)
    s = acts.add_parser("search", help="rank assets by query words (all words must match)")
    s.add_argument("query", nargs="+", help="words, e.g. police car")
    common(s, True)
    sh = acts.add_parser("show", help="full record for one or more ids")
    sh.add_argument("ids", nargs="+", help="asset ids, e.g. cars/police")
    common(sh, False)
    acts.add_parser("schema", help="describe every field and command (JSON)")
    inv.set_defaults(func=cmd_inventory)


def build_parser() -> argparse.ArgumentParser:
    """Builds the `buildoff` argument parser with one subparser per command."""
    p = JsonErrorParser(prog="buildoff", description="The $100 GTA Build-Off harness.")
    sub = p.add_subparsers(dest="command", required=True, parser_class=JsonErrorParser)

    sub.add_parser("doctor", help="check prerequisites").set_defaults(func=cmd_doctor)

    a = sub.add_parser("assets", help="rebuild assets/ from original sources")
    a.add_argument(
        "what",
        nargs="?",
        default="all",
        choices=["gpu", "cars", "props", "catalog", "mirror", "city", "dataset", "publish", "all"],
    )
    a.add_argument("--source", default=None, help="mirror only this source id")
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

    add_inventory(sub)

    f = sub.add_parser(
        "fetch",
        help="download assets from the HF dataset (pinned revision)",
        description=(
            "Download assets from the Hugging Face dataset at the pinned revision. "
            "Pass catalog ids (from `inventory search`), --core for the seeded set, or "
            "--pattern for dataset globs. Prints a JSON summary."
        ),
    )
    f.add_argument("ids", nargs="*", help="catalog ids, e.g. rocketbox-avatars/chef-female-01")
    f.add_argument("--core", action="store_true", help="the seeded set (~508 MB)")
    f.add_argument("--pattern", action="append", help="dataset glob, e.g. 'meta-mhr/*'")
    f.add_argument("--tiers", action="store_true", help="include people's lods/mobile/collision")
    f.add_argument("--out", type=Path, default=None, help="folder (default: HF cache)")
    f.set_defaults(func=cmd_fetch)
    return p


def main() -> None:
    """Entry point for the `buildoff` console script."""
    args = build_parser().parse_args()
    sys.exit(args.func(args))
