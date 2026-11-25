"""Seeds a contender's workspace with the starter project and the shared asset pack.

Both contenders must start from byte-identical folders. `harness.runner` calls
`seed_workspace` once per contender before turn 1. The result is:

    workspace/
      package.json, package-lock.json   Vite + three.js at exact versions (SEED_DIR)
      index.html, src/main.js           an empty three.js scene that builds and renders
      public/assets/gt-gpu/<dataset layout>   the seeded asset set (harness.fetch.PACK_PATTERNS)
      tools/assets.mjs, tools/catalog.json    the models' own search + fetch tool (full pack only)
      tools/screenshot                  build + render the game to a PNG (harness.shot_tool)
      .gitignore                        keeps node_modules/ and dist/ out of the model's own commits
      node_modules/                     from `npm ci`

and, next to the workspace, `toolkit/`: a stripped copy of the few harness
modules `tools/screenshot` and the Stop hook run. The model's sandbox
(`harness.sandbox`) lets it read that copy but not this repo, and models do
read it, so it carries code only: no docstrings or comments, and a config with
just the constants the tools use. Nothing in it says there's a race or who
else is in it.

The starter project lives in this repo (SEED_DIR). Up to prompt-v15 races
started from a third-party demo game instead; models spent their first turn
tearing it out, and one kept its demo character as the founder. The core assets
are downloaded once into the huggingface_hub cache and copied from there, so a
race doesn't re-download anything per contender.
"""

import ast
import fnmatch
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from harness import config, fetch
from harness.config import CATALOG_PATH, GAME_ASSETS_SUBDIR, REPO_ROOT

# node_modules is reinstalled per workspace; dist is rebuilt every turn. The
# harness's own per-turn history ignores them regardless (snapshot.EVIDENCE_EXCLUDES);
# this file only helps a model that runs git in its workspace itself.
WORKSPACE_GITIGNORE: str = "node_modules/\ndist/\ntools/shots/\n"

NPM_TIMEOUT_S: int = 600

# The models' zero-dependency asset tool, copied into every workspace's tools/.
TOOL_PATH: Path = REPO_ROOT / "harness" / "workspace_tools" / "assets.mjs"

# The starter project every workspace begins as: Vite and three.js pinned to
# exact versions by its lockfile, and a blank scene that passes the harness's
# build and playable checks.
SEED_DIR: Path = REPO_ROOT / "harness" / "workspace_tools" / "seed"

# The harness modules that run inside the model's sandbox: `tools/screenshot`
# (shot_tool -> snapshot -> config) and the Stop hook (harness.session).
# config.py and __init__.py aren't copied: `write_toolkit` generates them.
TOOLKIT_MODULES: tuple[str, ...] = (
    "cliutil.py",
    "shot_tool.py",
    "snapshot.py",
    "stop_hook.py",
)

# The only `harness.config` names the toolkit modules import. The real config
# names both contenders, the budget and the stop rules.
TOOLKIT_CONFIG_NAMES: tuple[str, ...] = ("BUILD_DIR", "GAME_ENTRY", "SCREENSHOT_SETTLE_MS")


def strip_source(source: str) -> str:
    """Returns the same code with every docstring and comment removed.

    The harness's docs explain the race (contenders, budget, critic), and a
    model that reads its toolkit shouldn't learn that from them. Round-tripping
    through the AST keeps the code's behaviour and drops comments by design.

    Args:
        source: a Python module's source

    Returns:
        equivalent source with no docstrings or comments
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (
            isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            # A body can't be empty, so a docstring-only one becomes `pass`.
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree) + "\n"


def write_toolkit(toolkit: Path) -> Path:
    """Writes the modules `tools/screenshot` and the Stop hook need into `toolkit/harness/`.

    They run inside the model's sandbox, which can't read this repo, so they
    get their own stripped copy outside the workspace (read-only to the model).

    Returns:
        the toolkit folder, for PYTHONPATH
    """
    package = toolkit / "harness"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "".join(f"{name} = {getattr(config, name)!r}\n" for name in TOOLKIT_CONFIG_NAMES)
    )
    for name in TOOLKIT_MODULES:
        source = (REPO_ROOT / "harness" / name).read_text()
        (package / name).write_text(strip_source(source))
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
        "# Usage: tools/screenshot [--hold KEYS:MS] [--wait MS] [--shot NAME] [--click X,Y]\n"
        "#        [--look DX,DY] ... [--out PATH] [--no-build] [--help]\n"
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


def seed_workspace(workspace: Path, toolkit: Path, pack: str = "full") -> None:
    """Fills an empty workspace with the starter project, our assets and installed deps.

    Args:
        workspace: the contender's folder; must not exist yet
        toolkit: where to put the screenshot tool's modules; must not exist yet
        pack: "full" (the whole seeded asset set plus the asset search tool) or
            "primitives" (only the GPU loot; no asset tool). Both get tools/screenshot.
    """
    shutil.copytree(SEED_DIR, workspace)
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
    # starter's lockfile, so both contenders get identical dependencies.
    subprocess.run(
        ["npm", "ci", "--no-audit", "--no-fund", "--loglevel=error"],
        cwd=workspace,
        check=True,
        timeout=NPM_TIMEOUT_S,
    )
