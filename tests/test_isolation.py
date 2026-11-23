"""The contender sandbox and environment scrub (harness.sandbox), on the real sandbox-exec."""

import subprocess
import sys
from pathlib import Path

import pytest

from harness import sandbox

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """A fake RUNS_ROOT with two contenders, a fake harness repo and ~/.claude/projects."""
    root = tmp_path.resolve()
    runs, repo, projects = root / "runs", root / "repo", root / "projects"
    paths = {
        "own": runs / "race" / "opus" / "workspace",
        "toolkit": runs / "race" / "opus" / "toolkit",
        "other": runs / "race" / "kimi" / "workspace",
        "logs": runs / "race" / "opus" / "logs",
        "repo": repo,
        "venv": repo / ".venv",
    }
    for p in paths.values():
        p.mkdir(parents=True)
    paths["own_project"] = projects / sandbox.project_slug(paths["own"])
    paths["other_project"] = projects / sandbox.project_slug(paths["other"])
    paths["repo_project"] = projects / sandbox.project_slug(repo)
    for key in ("own_project", "other_project", "repo_project"):
        paths[key].mkdir(parents=True)
    for key, p in list(paths.items()):
        (p / "file").write_text(key)
    monkeypatch.setattr(sandbox, "RUNS_ROOT", runs)
    monkeypatch.setattr(sandbox, "REPO_ROOT", repo)
    monkeypatch.setattr(sandbox, "CLAUDE_PROJECTS", projects)
    return paths


def _sh(profile: Path, cwd: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Runs a bash script under the profile."""
    return subprocess.run(
        sandbox.wrap(["bash", "-c", script], profile), cwd=cwd, capture_output=True, text=True
    )


@pytest.mark.parametrize("key", ["own", "toolkit", "venv", "own_project"])
def test_contender_can_read_its_own_paths(layout: dict[str, Path], key: str) -> None:
    """The workspace, toolkit, harness venv and own transcripts stay readable."""
    profile = sandbox.write_profile(
        layout["logs"].parent / "sandbox.sb", layout["own"], layout["toolkit"]
    )
    proc = _sh(profile, layout["own"], f"cat {layout[key] / 'file'}")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == key


@pytest.mark.parametrize("key", ["other", "logs", "repo", "other_project", "repo_project"])
def test_contender_cannot_read_anything_else(layout: dict[str, Path], key: str) -> None:
    """The other contender, the evidence, the harness repo and other transcripts are hidden."""
    profile = sandbox.write_profile(
        layout["logs"].parent / "sandbox.sb", layout["own"], layout["toolkit"]
    )
    proc = _sh(profile, layout["own"], f"cat {layout[key] / 'file'}")
    assert proc.returncode != 0
    assert "Operation not permitted" in proc.stderr


def test_writes_are_confined_to_the_workspace(layout: dict[str, Path]) -> None:
    """The model can write in its workspace but not into its toolkit or logs."""
    profile = sandbox.write_profile(
        layout["logs"].parent / "sandbox.sb", layout["own"], layout["toolkit"]
    )
    assert _sh(profile, layout["own"], "echo x > new").returncode == 0
    assert _sh(profile, layout["own"], f"echo x > {layout['toolkit'] / 'x'}").returncode != 0
    assert _sh(profile, layout["own"], f"echo x > {layout['logs'] / 'x'}").returncode != 0


def test_workspace_claude_config_is_read_only(layout: dict[str, Path]) -> None:
    """A model can't plant hooks, agents or MCP servers for its next turn."""
    profile = sandbox.write_profile(
        layout["logs"].parent / "sandbox.sb", layout["own"], layout["toolkit"]
    )
    blocked = "mkdir -p .claude && echo {} > .claude/settings.json"
    assert _sh(profile, layout["own"], blocked).returncode != 0
    assert _sh(profile, layout["own"], "echo {} > .mcp.json").returncode != 0
    assert _sh(profile, layout["own"], "echo notes > CLAUDE.md").returncode == 0


def test_clean_env_drops_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only allowlisted variables and the harness's own extras reach claude."""
    monkeypatch.setenv("FIREWORKS_API_KEY", "secret")
    monkeypatch.setenv("CLAUDECODE", "1")
    env = sandbox.clean_env({"CLAUDE_CODE_SUBAGENT_MODEL": "m"})
    assert "FIREWORKS_API_KEY" not in env
    assert "CLAUDECODE" not in env
    assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "m"
    assert env["PATH"]
