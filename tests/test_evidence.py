"""Per-turn evidence (harness.snapshot), meter parsing, status and the screenshot tool CLI."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from harness import meter, shot_tool, snapshot, status


def _tracked(history: Path, workspace: Path) -> set[str]:
    """Files in the latest evidence commit."""
    out = subprocess.run(
        ["git", f"--git-dir={history}", f"--work-tree={workspace}", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return set(out.split())


def test_history_ignores_model_gitignore_but_not_excludes(tmp_path: Path) -> None:
    """The history records files the model gitignored, and never node_modules or dist."""
    ws, history = tmp_path / "ws", tmp_path / "history.git"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "main.js").write_text("game")
    (ws / "secret.js").write_text("hidden from git")
    (ws / ".gitignore").write_text("secret.js\n")
    (ws / "node_modules" / "x").mkdir(parents=True)
    (ws / "node_modules" / "x" / "i.js").write_text("dep")
    (ws / "dist").mkdir()
    (ws / "dist" / "index.html").write_text("built")
    snapshot.init_history(history)
    sha = snapshot.commit(history, ws, "turn 1")
    assert len(sha) == 40
    assert _tracked(history, ws) == {".gitignore", "secret.js", "src/main.js"}
    assert not (ws / ".git").exists()


def test_history_survives_a_model_git_repo(tmp_path: Path) -> None:
    """A model's own `git init` in the workspace doesn't affect the evidence history."""
    ws, history = tmp_path / "ws", tmp_path / "history.git"
    ws.mkdir()
    (ws / "a.js").write_text("1")
    snapshot.init_history(history)
    snapshot.commit(history, ws, "turn 1")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    (ws / "b.js").write_text("2")
    snapshot.commit(history, ws, "turn 2")
    assert _tracked(history, ws) == {"a.js", "b.js"}
    log = subprocess.run(
        ["git", f"--git-dir={history}", "log", "--format=%s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    assert log[:2] == ["turn 2", "turn 1"]


def test_playable_ignores_console_noise() -> None:
    """Console errors alone don't fail a turn; an uncaught exception does."""
    ok = snapshot.ShotResult(True, True, True, page_errors=[], console_errors=["404 favicon"])
    assert ok.playable
    crashed = snapshot.ShotResult(True, True, True, page_errors=["TypeError: x is undefined"])
    assert not crashed.playable
    assert not snapshot.ShotResult(True, True, shot_written=False).playable


def test_parse_usage_folds_subagents() -> None:
    """Subagent rows count toward the models seen; cost comes from grandTotals."""
    data = {
        "rows": [{"displayModel": "a"}],
        "subagents": [{"rows": [{"displayModel": "b"}]}],
        "grandTotals": {"cost": "1.25"},
        "unpriced": 2,
    }
    reading = meter.parse_usage(data)
    assert reading == meter.Reading(cost_usd=1.25, models=frozenset({"a", "b"}), unpriced=2)
    with pytest.raises(KeyError):
        meter.parse_usage({"rows": []})


def test_status_sees_a_set_aside_done(tmp_path: Path) -> None:
    """declared_done stays true after the runner moves DONE.md into logs/."""
    folder = tmp_path / "opus"
    (folder / "logs").mkdir(parents=True)
    (folder / "workspace").mkdir()
    (folder / "logs" / "done-turn-001.md").write_text("done")
    (folder / "logs" / "turns.jsonl").write_text('{"turn": 0}\n{"turn": 1, "bu')
    report = status.contender_status(folder)
    assert report["declared_done"] is True
    assert report["turns_recorded"] == 0  # the half-written row is skipped


@pytest.mark.parametrize("spec", ["w", "w:", ":10", "w:0", "w:-5", "w:abc"])
def test_parse_hold_rejects_bad_specs(spec: str) -> None:
    """--hold needs KEY:MS with a positive MS."""
    with pytest.raises(argparse.ArgumentTypeError):
        shot_tool.parse_hold(spec)


def test_parse_hold_accepts_keys_with_colons() -> None:
    """The last colon separates the duration, so key names stay intact."""
    assert shot_tool.parse_hold("ArrowUp:500") == ("ArrowUp", 500)


def test_screenshot_tool_never_reports_a_stale_png(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed render after an earlier success reports ok: false, not the old file."""
    out = tmp_path / "shot.png"
    out.write_bytes(b"old")
    monkeypatch.setattr(
        shot_tool, "screenshot", lambda *a, **k: snapshot.ShotResult(True, True, False)
    )
    args = argparse.Namespace(workspace=tmp_path, out=out, hold=[], settle_ms=0, no_build=True)
    result = shot_tool.run(args)
    assert result["ok"] is False and result["png"] is None
    assert not out.exists()
    json.dumps(result)  # the tool prints this dict, so it must stay JSON-serialisable
