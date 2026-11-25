"""The Stop hook, per-contender settings, the cut-off retry rule and odd stream events."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness import runner, session, stop_hook, viewer
from harness.config import CONTENDERS


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


def test_hook_ignores_done_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DONE.md no longer ends a race, so it doesn't let an announcement through."""
    (tmp_path / "DONE.md").write_text("done")
    monkeypatch.setattr(stop_hook, "builds", lambda _ws: True)
    assert stop_hook.decide({"last_assistant_message": "I'll add more."}, tmp_path)


def test_hook_blocks_announcements_and_broken_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Block on an announcement or a failing build; otherwise allow the stop."""
    monkeypatch.setattr(stop_hook, "builds", lambda _ws: True)
    assert stop_hook.decide({"last_assistant_message": "I'll add the HUD next."}, tmp_path)
    assert not stop_hook.decide({"last_assistant_message": "Added the HUD."}, tmp_path)
    monkeypatch.setattr(stop_hook, "builds", lambda _ws: False)
    assert stop_hook.decide({"last_assistant_message": "Added the HUD."}, tmp_path)


def test_hook_cli_prints_block_with_the_locked_reason(tmp_path: Path) -> None:
    """End to end: the hook's JSON reason is the nudge template's fixed closing line."""
    reason = tmp_path / "reason.txt"
    reason.write_text(session.hook_reason() + "\n")
    payload = {"cwd": str(tmp_path), "last_assistant_message": "I'm now adding sirens."}
    proc = subprocess.run(
        [sys.executable, "-m", "harness.stop_hook", str(reason)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(proc.stdout)
    assert out == {"decision": "block", "reason": "Keep making the game better."}


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


def test_critic_settings_match_but_have_no_hook(tmp_path: Path) -> None:
    """The critic gets the builder's pins, effort and compaction, but no Stop hook."""
    model = CONTENDERS[0].model
    session.write(tmp_path, model)
    critic = json.loads((tmp_path / session.CRITIC_SETTINGS_FILE).read_text())
    assert critic == {"env": session.env(model)}


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


# Event shapes the turn-end checks must survive. A `permission_denied` system
# event with a string "message" crashed Opus out of the prompt-v15 race.
ODD_EVENTS: list[dict[str, object]] = [
    {"type": "system", "subtype": "permission_denied", "message": "Claude Code can't..."},
    {"type": "assistant", "message": None},
    {"type": "assistant", "message": {"content": "plain text"}},
    {"type": "assistant", "message": {"content": ["not a block", 3]}},
    {"type": "user", "message": ["a list"]},
    {"type": "result", "is_error": True, "result": None},
]


@pytest.mark.parametrize("odd", ODD_EVENTS)
def test_turn_end_checks_survive_odd_events(tmp_path: Path, odd: dict[str, object]) -> None:
    """Unexpected event shapes never raise in the checks that classify a turn's end."""
    tool = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}}
    log = _log(tmp_path, [tool, odd])
    assert not runner._ended_after_cut_off(log)
    assert not runner._ended_on_api_error(log)


@pytest.mark.parametrize("odd", ODD_EVENTS)
def test_viewer_survives_odd_events(tmp_path: Path, odd: dict[str, object]) -> None:
    """The live viewer skips event shapes it doesn't know instead of dying."""
    viewer._render(json.dumps({"t": 0, "event": odd}), tmp_path / "cost.csv")
