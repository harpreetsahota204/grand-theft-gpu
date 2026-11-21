"""Seeds a contender's workspace with the base game and the shared asset pack.

Both contenders must start from byte-identical folders. `harness.runner` calls
`seed_workspace` once per contender before turn 1. The result is:

    workspace/
      <base game at BASE_REPO_COMMIT>   minus its .git and duplicate top-level assets/
      public/assets/gt-gpu/{gpu,cars,props}   copied from this repo's assets/
      .gitignore                        keeps node_modules/ and dist/ out of turn commits
      node_modules/                     from `npm install`

The base repo is fetched once into a cache under `RUNS_ROOT/.cache` and copied
from there, so a race doesn't re-download its 71 MB per contender.
"""

import shutil
import subprocess
from pathlib import Path

from harness.config import (
    ASSETS_DIR,
    BASE_REPO_COMMIT,
    BASE_REPO_URL,
    GAME_ASSETS_SUBDIR,
    RUNS_ROOT,
)

# node_modules is reinstalled per workspace; dist is rebuilt every turn. Neither
# belongs in the per-turn commits that the scoring timeline is built from.
WORKSPACE_GITIGNORE: str = "node_modules/\ndist/\n"

NPM_TIMEOUT_S: int = 600


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


def seed_workspace(workspace: Path) -> None:
    """Fills an empty workspace with the base game, our assets and installed deps.

    Args:
        workspace: the contender's folder; must not exist yet
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
    shutil.copytree(ASSETS_DIR, workspace / GAME_ASSETS_SUBDIR)
    (workspace / ".gitignore").write_text(WORKSPACE_GITIGNORE)

    # Install before turn 1 so the model starts with a buildable project and the
    # first turn isn't charged for waiting on npm.
    subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
        cwd=workspace,
        check=True,
        timeout=NPM_TIMEOUT_S,
    )
