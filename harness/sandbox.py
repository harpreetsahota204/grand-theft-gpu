"""Per-contender isolation: a macOS sandbox profile and a scrubbed environment.

Each turn's `claude` process (and every shell, build and server it starts) runs
under `sandbox-exec` with a profile written by `write_profile`. Inside it a
model can read and write only its own workspace, plus read its own screenshot
toolkit and the harness's Python environment. It can't read:

- the race folder outside its workspace: the other contender's game, the logs,
  the screenshots and the evidence history (`history.git`)
- earlier races under `RUNS_ROOT`
- this harness repo: prompts, maintainer notes and CLAUDE.md files
- other sessions' transcripts in `~/.claude/projects` (the other contender's,
  earlier races', and the harness repo's own project memory)

The critic (`read_only=True`) can read the whole workspace but write only
`CRITIC_WRITABLE` (build output and its own screenshots), so it can't change the game.

A builder also can't write `.claude/` or `.mcp.json` in its workspace: Claude Code
would load hooks, agents or MCP servers from there on the next turn.

Everything else stays as it was (`allow default`), so Claude Code, npm, git,
Node and Playwright work normally. The profile can't hide
`~/.claude/settings.json`, because Claude Code itself must read it for Nexus
routing. `clean_env` removes secrets from the environment instead.

Both contenders get the same profile, with only their own paths differing.
"""

import json
import os
import re
import subprocess
from pathlib import Path

from harness.config import ENV_ALLOWLIST, REPO_ROOT, RUNS_ROOT

SANDBOX_EXEC: str = "/usr/bin/sandbox-exec"
CLAUDE_PROJECTS: Path = Path.home() / ".claude" / "projects"


def project_slug(path: Path) -> str:
    """Returns the folder name Claude Code uses under ~/.claude/projects for a cwd.

    Claude Code replaces every character other than a letter or digit with "-".
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _lit(path: Path) -> str:
    """Quotes a path as an SBPL string literal (same escaping rules as JSON)."""
    return json.dumps(str(path))


def _regex_prefix(path: str) -> str:
    """An SBPL regex literal matching every path that starts with `path`."""
    return '#"^' + re.escape(path).replace('"', '\\"') + '"'


# What a read-only (critic) session may still write in the workspace: the build
# output and Vite's cache (tools/screenshot rebuilds into dist/) and its own shots.
CRITIC_WRITABLE: tuple[str, ...] = ("dist", "node_modules/.vite", "tools/shots")


def profile(workspace: Path, toolkit: Path, read_only: bool = False) -> str:
    """Builds the SBPL profile for one contender's builder or critic sessions.

    In SBPL the last matching rule wins, so each broad deny comes before the
    narrower allows that carve the contender's own paths back out of it.

    Args:
        workspace: the contender's game folder
        toolkit: the contender's screenshot toolkit (read-only)
        read_only: True for the critic: it can read the whole workspace but
            write only `CRITIC_WRITABLE`, so it can play the game but not edit it

    Returns:
        the profile text
    """
    runs, repo = RUNS_ROOT.resolve(), REPO_ROOT.resolve()
    workspace, toolkit = workspace.resolve(), toolkit.resolve()
    own_project = CLAUDE_PROJECTS / project_slug(workspace)
    # Metadata (stat, realpath) stays allowed so path resolution works; only
    # reading file contents, listing folders and writing are denied.
    deny = "(deny file-read-data file-write*"
    return "\n".join(
        [
            "(version 1)",
            "(allow default)",
            f"{deny} (subpath {_lit(runs)}))",
            f"{deny} (subpath {_lit(repo)}))",
            # Transcripts of every race session, and the harness repo's project memory.
            f"{deny} (regex {_regex_prefix(str(CLAUDE_PROJECTS / project_slug(runs)))}))",
            f"{deny} (subpath {_lit(CLAUDE_PROJECTS / project_slug(repo))}))",
            *(
                [f"(allow file-read-data (subpath {_lit(workspace)}))"]
                + [
                    f"(allow file-write* (subpath {_lit(workspace / sub)}))"
                    for sub in CRITIC_WRITABLE
                ]
                if read_only
                else [f"(allow file-read-data file-write* (subpath {_lit(workspace)}))"]
            ),
            # Project-level Claude Code config would load on the model's next
            # turn (hooks, agents, MCP servers); the harness sets those itself.
            f"(deny file-write* (subpath {_lit(workspace / '.claude')}))",
            f"(deny file-write* (literal {_lit(workspace / '.mcp.json')}))",
            f"(allow file-read-data file-write* (subpath {_lit(own_project)}))",
            f"(allow file-read-data (subpath {_lit(toolkit)}))",
            # The interpreter and packages tools/screenshot runs on.
            f"(allow file-read-data (subpath {_lit(repo / '.venv')}))",
            "",
        ]
    )


def write_profile(path: Path, workspace: Path, toolkit: Path, read_only: bool = False) -> Path:
    """Writes a contender's profile to `path` (outside its workspace) and returns it."""
    path.write_text(profile(workspace, toolkit, read_only))
    return path


def wrap(cmd: list[str], profile_path: Path) -> list[str]:
    """Prefixes argv so it runs under the given sandbox profile."""
    return [SANDBOX_EXEC, "-f", str(profile_path), *cmd]


def clean_env(extra: dict[str, str]) -> dict[str, str]:
    """The environment for a contender's `claude`: the allowlist plus `extra`.

    Args:
        extra: variables the harness sets on purpose, e.g. the subagent model

    Returns:
        a new environment dict
    """
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOWLIST}
    return env | extra


def check() -> str | None:
    """Returns an error message if sandbox-exec can't enforce a profile here."""
    if not Path(SANDBOX_EXEC).exists():
        return f"{SANDBOX_EXEC} not found (macOS only)"
    probe = subprocess.run(
        [SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return None if probe.returncode == 0 else f"sandbox-exec failed: {probe.stderr.strip()}"
