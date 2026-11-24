"""The read-only race views in harness.status."""

import json
from pathlib import Path

from harness import status


def test_review_trace_merges_tier4_checks(tmp_path: Path) -> None:
    """A round's verdict and its Tier 4 check row become one entry, in turn order."""
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"turn": 2, "tier": 4, "tier4_complete": True, "notes": "b", "critic_shots": ["d.png"]},
        {"turn": 2, "tier4_checks": {"passed": False, "failures": ["frozen"]}},
        {"turn": 1, "tier": 2, "tier4_complete": False, "notes": "a", "critic_shots": []},
    ]
    (logs / "reviews.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    trace = status.review_trace(tmp_path)
    assert [r["turn"] for r in trace] == [1, 2]
    assert trace[0]["critic_shots"] is None
    assert trace[1]["tier4_checks"]["failures"] == ["frozen"]
    assert trace[1]["critic_shot_count"] == 1
