"""Stop rules, watchdog helpers and process cleanup in harness.runner."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from harness import meter, runner
from harness.runner import ContenderRun


def _critic_log(tmp_path: Path, final: str) -> Path:
    """Writes a critic transcript whose final result message is `final`."""
    path = tmp_path / "critic.jsonl"
    event = {"type": "result", "subtype": "success", "result": final}
    path.write_text(json.dumps({"t": 1, "event": event}) + "\n")
    return path


def test_review_verdict_is_parsed_from_the_last_line(tmp_path: Path) -> None:
    """The JSON line that ends the critic's reply becomes the Review."""
    verdict = {
        "tier": 3,
        "tier4_complete": False,
        "day_shot": "",
        "night_shot": "",
        "notes": "Traffic never moves; add {cars} on the main road.",
    }
    review = runner.parse_review(_critic_log(tmp_path, "Played it.\n" + json.dumps(verdict)))
    assert review == runner.Review(
        parsed=True, tier=3, tier4_complete=False, notes=verdict["notes"]
    )


def test_review_verdict_inside_a_code_fence(tmp_path: Path) -> None:
    """A verdict wrapped in a code fence still parses."""
    final = (
        '```json\n{"tier": 4, "tier4_complete": true, "day_shot": "a.png", '
        '"night_shot": "b.png", "notes": "Polish."}\n```'
    )
    review = runner.parse_review(_critic_log(tmp_path, final))
    assert review.parsed and review.tier4_complete and review.night_shot == "b.png"


def test_missing_verdict_is_unparsed(tmp_path: Path) -> None:
    """No verdict line means an unparsed review; the builder gets NO_REVIEW_NOTES."""
    assert not runner.parse_review(_critic_log(tmp_path, "I ran out of time.")).parsed
    assert runner.NO_REVIEW_NOTES in runner.nudge_text("")


def test_nudge_wraps_the_critics_notes() -> None:
    """The locked template carries the notes verbatim and ends on its fixed line."""
    text = runner.nudge_text("Fix the siren.")
    assert "Fix the siren." in text and "{notes}" not in text
    assert text.strip().endswith("Keep building the game toward Tier 4.")


def test_critic_prompt_contains_the_brief(tmp_path: Path) -> None:
    """The critic sees the same game brief the builder got."""
    spec = tmp_path / "spec.md"
    spec.write_text("# Grand Theft GPU\nSteal a GPU.")
    text = runner.critic_text(spec)
    assert "Steal a GPU." in text and "{brief}" not in text


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
