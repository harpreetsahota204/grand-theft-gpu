"""The Stop hook, the per-contender Claude Code settings, and the cut-off retry rule."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness import runner, session, stop_hook
from harness.config import CONTENDERS, PROMPTS_DIR


@pytest.mark.parametrize(
    "message",
    [
        "I’m adding deterministic browser checks now, then I’ll fix any failures.",
        "Next, I wire the police chase.",
        "Let me run the build again.",
        "I'm going to add traffic lights.",
    ],
)
def test_announcements_are_caught(message: str) -> None:
    """Closing lines that promise work, including Kimi's curly apostrophe, count."""
    assert stop_hook.announces_work(message)


@pytest.mark.parametrize(
    "message",
    [
        "I added three missions and a wanted system. The build passes.",
        "Done: the game is finished and DONE.md describes how to play.",
        "Now it works end to end.",
    ],
)
def test_reports_are_not_announcements(message: str) -> None:
    """Past-tense reports of finished work don't trigger the hook."""
    assert not stop_hook.announces_work(message)


def test_hook_lets_a_finished_model_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With DONE.md present the hook never blocks, even on an announcement."""
    (tmp_path / "DONE.md").write_text("done")
    monkeypatch.setattr(stop_hook, "builds", lambda _ws: False)
    assert not stop_hook.decide({"last_assistant_message": "I'll add more."}, tmp_path)


def test_hook_blocks_announcements_and_broken_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without DONE.md: block on an announcement, or on a failing build; else allow."""
    monkeypatch.setattr(stop_hook, "builds", lambda _ws: True)
    assert stop_hook.decide({"last_assistant_message": "I'll add the HUD next."}, tmp_path)
    assert not stop_hook.decide({"last_assistant_message": "Added the HUD."}, tmp_path)
    monkeypatch.setattr(stop_hook, "builds", lambda _ws: False)
    assert stop_hook.decide({"last_assistant_message": "Added the HUD."}, tmp_path)


def test_hook_cli_prints_block_with_the_locked_nudge(tmp_path: Path) -> None:
    """End to end: the hook's JSON reason is exactly the locked nudge text."""
    nudge = tmp_path / "nudge.txt"
    nudge.write_text((PROMPTS_DIR / "nudge.md").read_text())
    payload = {"cwd": str(tmp_path), "last_assistant_message": "I'm now adding sirens."}
    proc = subprocess.run(
        [sys.executable, "-m", "harness.stop_hook", str(nudge)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out == {"decision": "block", "reason": nudge.read_text().strip()}


def test_settings_differ_only_by_model(tmp_path: Path) -> None:
    """Both contenders get the same settings and agents, apart from their own model ID."""
    kimi, opus = (session.settings(c.model, tmp_path) for c in CONTENDERS)
    swapped = json.loads(json.dumps(kimi).replace(CONTENDERS[0].model, CONTENDERS[1].model))
    assert swapped == opus
    env = opus["env"]
    assert isinstance(env, dict)
    tiers = [k for k in env if k.startswith("ANTHROPIC_DEFAULT_")]
    assert len(tiers) == 4 and all(env[k] == CONTENDERS[1].model for k in tiers)
    assert env["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"] == "1"


def test_playtester_cannot_edit() -> None:
    """The one custom subagent can read and run tools/screenshot but not edit."""
    tester = session.agents()["playtester"]
    assert isinstance(tester, dict)
    assert set(tester["disallowedTools"]) == {"Edit", "Write"}
    assert tester["model"] == "inherit"


def _log(tmp_path: Path, events: list[dict[str, object]]) -> Path:
    """Writes events as a runner turn log."""
    path = tmp_path / "turn.jsonl"
    path.write_text("".join(json.dumps({"t": i, "event": e}) + "\n" for i, e in enumerate(events)))
    return path


def test_cut_off_turn_with_no_work_is_retried(tmp_path: Path) -> None:
    """A stream cut off with no tool call afterwards is an infrastructure retry."""

    def msg(role: str, block: dict[str, str]) -> dict[str, object]:
        """One stream-json event with a single content block."""
        return {"type": role, "message": {"content": [block]}}

    cut = msg("user", {"type": "text", "text": "Your response above was cut off mid-stream."})
    text = msg("assistant", {"type": "text", "text": "I'm adding checks."})
    tool = msg("assistant", {"type": "tool_use", "name": "Bash"})
    assert runner._ended_after_cut_off(_log(tmp_path, [tool, cut, text]))
    assert not runner._ended_after_cut_off(_log(tmp_path, [cut, tool, text]))
    assert not runner._ended_after_cut_off(_log(tmp_path, [tool, text]))
