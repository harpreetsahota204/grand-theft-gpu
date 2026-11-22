"""Stop rules, watchdog helpers and process cleanup in harness.runner."""

import dataclasses
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from harness import meter, runner
from harness.config import MAX_NUDGES
from harness.runner import ContenderRun


@pytest.mark.parametrize("end", ["budget", "leak", "meter_down", "aborted", "error"])
def test_hard_stops_end_the_run(run: ContenderRun, end: runner.TurnEnd) -> None:
    """Hard limits stop the run whatever the nudge count or DONE.md."""
    (run.workspace / "DONE.md").write_text("done")
    assert run._stop_reason(end, nudges=0, turn=1) == end


def test_api_error_after_retries_is_error(run: ContenderRun) -> None:
    """The loop retries api_error first; reaching the stop rules means retries ran out."""
    assert run._stop_reason("api_error", nudges=0, turn=1) == "error"


def test_early_done_is_set_aside_and_nudged(run: ContenderRun) -> None:
    """A DONE.md before the last nudge moves to logs/ and the model is nudged on."""
    (run.workspace / "DONE.md").write_text("done")
    assert run._stop_reason("completed", nudges=0, turn=2) is None
    assert not (run.workspace / "DONE.md").exists()
    assert (run.logs / "done-turn-002.md").read_text() == "done"
    assert run._done_declared == [{"turn": 2, "cost_usd": 0.0}]


def test_done_after_last_nudge_stops(run: ContenderRun) -> None:
    """With the nudges used up, DONE.md ends the run as declared_done."""
    (run.workspace / "DONE.md").write_text("done")
    assert run._stop_reason("completed", nudges=MAX_NUDGES, turn=5) == "declared_done"


def test_smoke_mode_stops_on_first_done(run: ContenderRun) -> None:
    """With nudge_on_done off (smoke test), the first DONE.md ends the run."""
    run.cfg = dataclasses.replace(run.cfg, nudge_on_done=False)
    (run.workspace / "DONE.md").write_text("done")
    assert run._stop_reason("completed", nudges=0, turn=1) == "declared_done"


def test_nudge_cap(run: ContenderRun) -> None:
    """No DONE.md and no nudges left ends the run as nudge_cap; otherwise nudge."""
    assert run._stop_reason("stalled", nudges=MAX_NUDGES - 1, turn=3) is None
    assert run._stop_reason("completed", nudges=MAX_NUDGES, turn=4) == "nudge_cap"


def test_meter_fails_closed(run: ContenderRun, monkeypatch: pytest.MonkeyPatch) -> None:
    """No reading is tolerated briefly, then stops the turn as meter_down."""
    monkeypatch.setattr(meter, "read_session", lambda _sid: None)
    run._last_reading_at = time.monotonic()
    assert run._check_meter() is None
    run._last_reading_at = time.monotonic() - runner.METER_BLIND_LIMIT_S - 1
    assert run._check_meter() == "meter_down"
    events = (run.logs / "events.jsonl").read_text()
    assert '"meter_down"' in events


def test_meter_budget_and_leak(run: ContenderRun, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spend at the cap stops as budget; a foreign model stops as leak."""
    own = run.contender.nexus_model
    reading = meter.Reading(cost_usd=1.0, models=frozenset({own}), unpriced=0)
    monkeypatch.setattr(meter, "read_session", lambda _sid: reading)
    assert run._check_meter() == "budget"
    reading = meter.Reading(cost_usd=0.1, models=frozenset({own, "other"}), unpriced=0)
    assert run._check_meter() == "leak"


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
