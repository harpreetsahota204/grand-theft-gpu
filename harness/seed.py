"""Seeds a contender's workspace with the base game and the shared asset pack.

Both contenders must start from byte-identical folders. `harness.runner` calls
`seed_workspace` once per contender before turn 1. The result is:

    workspace/
      <base game at BASE_REPO_COMMIT>   minus its .git and duplicate top-level assets/
      public/assets/gt-gpu/<dataset layout>   the seeded asset set (harness.fetch.PACK_PATTERNS)
      tools/assets.mjs, tools/catalog.json    the models' own search + fetch tool (full pack only)
      tools/screenshot                  build + render the game to a PNG (harness.shot_tool)
      .gitignore                        keeps node_modules/ and dist/ out of the model's own commits
      node_modules/                     from `npm ci`

and, next to the workspace, `toolkit/`: a copy of the few harness modules
`tools/screenshot` runs. The model's sandbox (`harness.sandbox`) lets it read
that copy but not this repo.

The base repo is fetched once into a cache under `RUNS_ROOT/.cache`, and the
core assets once into the huggingface_hub cache; both are copied from there,
so a race doesn't re-download anything per contender.
"""

import fnmatch
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from harness import fetch
from harness.catalog import CATALOG_PATH
from harness.config import (
    BASE_REPO_COMMIT,
    BASE_REPO_URL,
    GAME_ASSETS_SUBDIR,
    REPO_ROOT,
    RUNS_ROOT,
)

# node_modules is reinstalled per workspace; dist is rebuilt every turn. The
# harness's own per-turn history ignores them regardless (snapshot.EVIDENCE_EXCLUDES);
# this file only helps a model that runs git in its workspace itself.
WORKSPACE_GITIGNORE: str = "node_modules/\ndist/\ntools/shots/\n"

NPM_TIMEOUT_S: int = 600

# The models' zero-dependency asset tool, copied into every workspace's tools/.
TOOL_PATH: Path = REPO_ROOT / "harness" / "workspace_tools" / "assets.mjs"

# The harness modules that run inside the model's sandbox: `tools/screenshot`
# (shot_tool -> snapshot -> config) and the Stop hook (harness.session).
TOOLKIT_MODULES: tuple[str, ...] = (
    "__init__.py",
    "cliutil.py",
    "config.py",
    "shot_tool.py",
    "snapshot.py",
    "stop_hook.py",
)


def write_toolkit(toolkit: Path) -> Path:
    """Copies the modules `tools/screenshot` needs into `toolkit/harness/`.

    The screenshot tool runs inside the model's sandbox, which can't read this
    repo, so it gets its own copy outside the workspace (read-only to the model).

    Returns:
        the toolkit folder, for PYTHONPATH
    """
    package = toolkit / "harness"
    package.mkdir(parents=True)
    for name in TOOLKIT_MODULES:
        shutil.copy2(REPO_ROOT / "harness" / name, package / name)
    return toolkit


def write_screenshot_wrapper(workspace: Path, toolkit: Path) -> Path:
    """Writes `tools/screenshot`, which runs `harness.shot_tool` on this workspace.

    The wrapper pins this harness's Python interpreter and the contender's
    toolkit copy, so the model can call it from Bash without any setup. Both
    contenders get an identical script apart from their own paths.

    Returns:
        path of the executable wrapper
    """
    script = workspace / "tools" / "screenshot"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# Build the game and save a gameplay screenshot (JSON result on stdout).\n"
        "# Usage: tools/screenshot [--hold KEY:MS ...] [--out PATH] [--no-build] [--help]\n"
        f"PYTHONPATH={shlex.quote(str(toolkit.resolve()))} exec {shlex.quote(sys.executable)} "
        f'-m harness.shot_tool {shlex.quote(str(workspace.resolve()))} "$@"\n'
    )
    script.chmod(0o755)
    return script


def copy_core(dest: Path, patterns: list[str] = fetch.CORE_PATTERNS) -> int:
    """Copies the seeded asset set (dataset layout) into dest.

    Only files matching `patterns` are copied: the huggingface_hub cache can
    also hold extras someone fetched on demand, and those must never leak into
    one race but not another.

    Args:
        dest: the workspace's asset folder
        patterns: which dataset files to seed (see `fetch.PACK_PATTERNS`)

    Returns:
        files copied
    """
    src = fetch.core()
    copied = 0
    for path in sorted(src.rglob("*")):
        rel_path = path.relative_to(src)
        rel = rel_path.as_posix()
        # Check `.cache` relative to the snapshot: the HF cache itself lives under
        # ~/.cache, so testing the absolute path would skip every file.
        if path.is_dir() or ".cache" in rel_path.parts:
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # copy2 follows the cache's symlinks, so the workspace gets real files.
            shutil.copy2(path, target)
            copied += 1
    return copied


def base_cache() -> Path:
    """Returns a local checkout of the base game at the pinned commit, fetching it once.

    Fetches only that one commit (depth 1), which GitHub allows by SHA.

    Returns:
        path to the cached checkout
    """
    cache = RUNS_ROOT / ".cache" / f"base-{BASE_REPO_COMMIT[:7]}"
    if (cache / "package.json").exists():
        return cache

    # Fetch into a temp sibling and rename at the end, so an interrupted fetch
    # never leaves a half-populated cache that looks valid.
    tmp = cache.with_name(cache.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "remote", "add", "origin", BASE_REPO_URL],
        ["git", "fetch", "-q", "--depth", "1", "origin", BASE_REPO_COMMIT],
        ["git", "checkout", "-q", "FETCH_HEAD"],
    ):
        subprocess.run(cmd, cwd=tmp, check=True)
    tmp.rename(cache)
    return cache


def seed_workspace(workspace: Path, toolkit: Path, pack: str = "full") -> None:
    """Fills an empty workspace with the base game, our assets and installed deps.

    Args:
        workspace: the contender's folder; must not exist yet
        toolkit: where to put the screenshot tool's modules; must not exist yet
        pack: "full" (the whole seeded asset set plus the asset search tool) or
            "primitives" (only the GPU loot; no asset tool). Both get tools/screenshot.
    """
    cache = base_cache()

    # At the repo root, drop three things the base repo commits:
    # - assets/: a duplicate of public/assets/ (90 MB of it is city.glb); the
    #   game only loads from public/assets/
    # - node_modules/: committed without execute bits and with another OS's
    #   native binaries, so `vite` fails with "Permission denied". A smoke test
    #   showed one model spending budget repairing it; a clean install is fair.
    # - dist/: stale build output; the harness rebuilds every turn
    def skip(directory: str, names: list[str]) -> set[str]:
        """Ignores .git everywhere, and assets/, node_modules/ and dist/ at the root."""
        skipped = {".git"} & set(names)
        if Path(directory) == cache:
            skipped |= {"assets", "node_modules", "dist"} & set(names)
        return skipped

    shutil.copytree(cache, workspace, ignore=skip)
    copy_core(workspace / GAME_ASSETS_SUBDIR, fetch.PACK_PATTERNS[pack])
    tools = workspace / "tools"
    # tools/shots exists up front: the read-only critic may write there but
    # can't create folders elsewhere in the workspace.
    (tools / "shots").mkdir(parents=True)
    if pack == "full":
        shutil.copy2(TOOL_PATH, tools / "assets.mjs")
        shutil.copy2(CATALOG_PATH, tools / "catalog.json")
    write_screenshot_wrapper(workspace, write_toolkit(toolkit))
    (workspace / ".gitignore").write_text(WORKSPACE_GITIGNORE)

    # Install before turn 1 so the model starts with a buildable project and the
    # first turn isn't charged for waiting on npm. `npm ci` installs exactly the
    # base game's lockfile, so both contenders get identical dependencies.
    subprocess.run(
        ["npm", "ci", "--no-audit", "--no-fund", "--loglevel=error"],
        cwd=workspace,
        check=True,
        timeout=NPM_TIMEOUT_S,
    )
