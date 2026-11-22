"""Shared fixtures: a ContenderRun wired to temporary folders, touching nothing real."""

from pathlib import Path

import pytest

from harness.config import CONTENDERS, RaceConfig
from harness.runner import ContenderRun


@pytest.fixture
def run(tmp_path: Path) -> ContenderRun:
    """A ContenderRun whose workspace and logs live under tmp_path (no seeding)."""
    cfg = RaceConfig(spec_path=tmp_path / "spec.md", budget_usd=1.0, race_id="test")
    r = ContenderRun(CONTENDERS[0], cfg)
    r.root = tmp_path / "contender"
    r.workspace = r.root / "workspace"
    r.logs = r.root / "logs"
    r.workspace.mkdir(parents=True)
    r.logs.mkdir(parents=True)
    return r
