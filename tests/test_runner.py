"""Stop rules, watchdog helpers and process cleanup in harness.runner."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from harness import meter, runner
from harness.runner import ContenderRun


def _verdict(tmp_path: Path, verdict: object) -> Path:
    """Writes a critic's verdict.json and returns its path."""
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(verdict))
    return path


GOOD_VERDICT: dict[str, object] = {
    "tier": 3,
    "tier4_complete": False,
    "day_shot": "",
    "night_shot": "",
    "notes": [
        {"group": "blocker", "note": "Pressing E near a cop car freezes the game."},
        {"group": "look and feel", "note": "Night is too dark to read the HUD."},
    ],
}


def test_review_verdict_is_read_from_the_file(tmp_path: Path) -> None:
    """A valid verdict.json becomes the Review, notes ranked and labelled."""
    review = runner.parse_review(_verdict(tmp_path, GOOD_VERDICT))
    assert review == runner.Review(
        parsed=True,
        tier=3,
        tier4_complete=False,
        notes="1. [blocker] Pressing E near a cop car freezes the game.\n"
        "2. [look and feel] Night is too dark to read the HUD.",
    )


def test_missing_verdict_is_unparsed(tmp_path: Path) -> None:
    """No verdict file means an unparsed review; the builder gets NO_REVIEW_NOTES."""
    review = runner.parse_review(tmp_path / "verdict.json")
    assert not review.parsed and review.problem == "no verdict.json"
    assert runner.NO_REVIEW_NOTES in runner.nudge_text("", 0.0, 25.0)


def test_verdict_that_is_not_json_is_unparsed(tmp_path: Path) -> None:
    """A truncated or prose verdict file is rejected with a reason."""
    path = tmp_path / "verdict.json"
    path.write_text('{"tier": 3, "notes": [')
    review = runner.parse_review(path)
    assert not review.parsed and "not JSON" in review.problem


@pytest.mark.parametrize(
    "change",
    [
        {"tier": 5},
        {"tier": True},
        {"tier": "3"},
        {"tier4_complete": "yes"},
        {"day_shot": 1},
        {"notes": []},
        {"notes": "Fix the siren."},
        {"notes": [{"group": "urgent", "note": "Fix the siren."}]},
        {"notes": [{"group": "polish", "note": "  "}]},
    ],
)
def test_verdict_off_schema_is_unparsed(tmp_path: Path, change: dict[str, object]) -> None:
    """Every schema break is rejected, never half-read."""
    review = runner.parse_review(_verdict(tmp_path, GOOD_VERDICT | change))
    assert not review.parsed and review.problem


def test_nudge_wraps_the_critics_notes_and_spend() -> None:
    """The locked template carries the notes and spend, and ends on its fixed line."""
    text = runner.nudge_text("Fix the siren.", 12.403, 100.0)
    assert "Fix the siren." in text and "{notes}" not in text
    assert "You have spent $12.40 of your $100." in text
    assert text.strip().endswith("Keep making the game better.")


def test_critic_prompt_contains_the_brief(tmp_path: Path) -> None:
    """The critic sees the same game brief the builder got, budget filled in."""
    spec = tmp_path / "spec.md"
    spec.write_text("# Grand Theft GPU\nSteal a GPU with {budget}.")
    text = runner.critic_text(spec, 25.0)
    assert "Steal a GPU with $25." in text and "{brief}" not in text


@pytest.mark.parametrize("pack", ["game_spec.md", "game_spec_primitives.md"])
def test_specs_state_the_real_budget(pack: str) -> None:
    """Both specs take the race's budget instead of a fixed $100."""
    text = runner.build_first_prompt(runner.PROMPTS_DIR / pack, 25.0)
    assert "about **$25 of compute**" in text
    assert "{budget}" not in text and "$100" not in text


def test_meter_fails_closed(run: ContenderRun, monkeypatch: pytest.MonkeyPatch) -> None:
    """No reading is tolerated briefly, then stops the turn as meter_down."""
    monkeypatch.setattr(meter, "read_session", lambda _sid: None)
    run._last_reading_at = time.monotonic()
    assert run._check_meter("s1") is None
    run._last_reading_at = time.monotonic() - runner.METER_BLIND_LIMIT_S - 1
    assert run._check_meter("s1") == "meter_down"
    events = (run.logs / "events.jsonl").read_text()
    assert '"meter_down"' in events


def test_meter_budget_and_leak(run: ContenderRun, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spend at the cap stops as budget; a foreign model stops as leak."""
    own = run.contender.nexus_model
    reading = meter.Reading(cost_usd=1.0, models=frozenset({own}), unpriced=0)
    # The lambda reads `reading` when called, so reassigning it below changes the result.
    monkeypatch.setattr(meter, "read_session", lambda _sid: reading)
    assert run._check_meter("s1") == "budget"
    reading = meter.Reading(cost_usd=0.1, models=frozenset({own, "other"}), unpriced=0)
    assert run._check_meter("s1") == "leak"


def test_budget_counts_every_session(run: ContenderRun, monkeypatch: pytest.MonkeyPatch) -> None:
    """Builder and critic sessions add up against one budget (here $1.00)."""
    own = frozenset({run.contender.nexus_model})
    costs = {"builder": 0.6, "critic-1": 0.3, "critic-2": 0.2}
    monkeypatch.setattr(meter, "read_session", lambda sid: meter.Reading(costs[sid], own, 0))
    assert run._check_meter("builder") is None
    assert run._check_meter("critic-1") is None
    assert run._check_meter("critic-2") == "budget"
    assert run._cost() == pytest.approx(1.1)


def test_api_error_detection(tmp_path: Path) -> None:
    """Only a final error result starting with 'API Error' counts; cut-off lines are skipped."""
    log = tmp_path / "turn.jsonl"
    result = {"type": "result", "is_error": True, "result": "API Error: stream stopped"}
    log.write_text(json.dumps({"t": 1, "event": result}) + "\n" + '{"t": 2, "ev')
    assert runner._ended_on_api_error(log)
    result["result"] = "something else"
    log.write_text(json.dumps({"t": 1, "event": result}) + "\n")
    assert not runner._ended_on_api_error(log)


def test_lsof_parsing_finds_only_workspace_processes(tmp_path: Path) -> None:
    """Processes inside the workspace are strays; a sibling folder with a shared prefix isn't."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    root = str(ws.resolve())
    out = f"p10\nn{root}\np11\nn{root}/src\np12\nn{root}-other\np13\nn/\np14\nn{root}\n"
    pairs = runner.parse_lsof_cwds(out)
    assert runner.strays_in(pairs, ws, own_pid=14) == [10, 11]


def test_kill_group_kills_background_children() -> None:
    """kill_group takes down a whole session, including a backgrounded child."""
    proc = subprocess.Popen(
        ["bash", "-c", "sleep 300 & echo $!; wait"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert proc.stdout is not None
    child = int(proc.stdout.readline())
    runner.kill_group(proc.pid, grace_s=5)
    proc.wait(timeout=5)
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


def test_critic_shots_are_kept_per_round(tmp_path: Path) -> None:
    """Only shots taken since the critic started are copied out of the workspace."""
    shots = tmp_path / "ws" / "tools" / "shots"
    shots.mkdir(parents=True)
    old = shots / "old.png"
    old.write_bytes(b"x")
    os.utime(old, (1000, 1000))
    (shots / "night.png").write_bytes(b"y")
    dest = tmp_path / "shots" / "critic-001"
    kept = runner.keep_critic_shots(tmp_path / "ws", dest, since=2000)
    assert kept == ["night.png"]
    assert (dest / "night.png").read_bytes() == b"y"
    assert not (dest / "old.png").exists()


def test_no_critic_shots_makes_no_folder(tmp_path: Path) -> None:
    """A critic that took no shots leaves no empty folder behind."""
    dest = tmp_path / "shots" / "critic-001"
    assert runner.keep_critic_shots(tmp_path / "ws", dest, since=0) == []
    assert not dest.exists()
