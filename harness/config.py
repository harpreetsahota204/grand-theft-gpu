"""Race configuration: who races, under what limits, and where outputs land.

The harness modules read their constants from here, so the rules of the race
live in one place. `harness.race` builds a `RaceConfig` from CLI flags;
`harness.runner` consumes it.
"""

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
PROMPTS_DIR: Path = REPO_ROOT / "prompts"

# Race workspaces live outside this repo so Claude Code never walks up into a
# CLAUDE.md or project memory that belongs to the harness, not the contestants.
RUNS_ROOT: Path = Path.home() / "gta-race-runs"

# Same tool set for both sides. Agent is allowed because a leak test showed
# subagents stay on their parent's model when pinned per process.
TOOLS: tuple[str, ...] = ("Bash", "Read", "Edit", "Write", "WebFetch", "WebSearch", "Agent")

# When a model ends its turn without declaring done, the harness sends the fixed
# nudge. After this many nudges the run ends, so "the model called it done" stays
# meaningful.
MAX_NUDGES: int = 3

# How often the watchdog asks Nexus for spend during a turn. Subagents can burn a
# few dollars between polls, so expect final spend slightly over budget.
METER_POLL_SECONDS: float = 15.0

# Contract files the run rules tell each model about.
DONE_FILE: str = "DONE.md"
GAME_ENTRY: str = "index.html"

# How long the game page gets to boot before the snapshot is taken, in ms.
SCREENSHOT_SETTLE_MS: int = 3000


@dataclass(frozen=True)
class Contender:
    """One side of the race.

    Attributes:
        name: short label used in paths, logs and the viewer title
        model: value passed to Claude Code's `--model` (and pinned for subagents)
        nexus_model: the `displayModel` Nexus reports for this model; any other
            model appearing in this contender's usage means a cross-model leak
    """

    name: str
    model: str
    nexus_model: str


CONTENDERS: tuple[Contender, ...] = (
    Contender(name="kimi", model="kimi-latest", nexus_model="kimi-k3p1-pro"),
    Contender(name="opus", model="opus", nexus_model="claude-opus-5-5"),
)


@dataclass(frozen=True)
class RaceConfig:
    """Settings for one race, built by `harness.race` from CLI flags.

    Attributes:
        spec_path: markdown file with the game spec both models receive
        budget_usd: hard spend cap per contender, at list price per Nexus
        race_id: folder name under `RUNS_ROOT` for this race's outputs
        open_viewers: whether to open a Terminal window per contender
        contenders: who races
    """

    spec_path: Path
    budget_usd: float
    race_id: str
    open_viewers: bool = True
    contenders: tuple[Contender, ...] = CONTENDERS

    @property
    def race_dir(self) -> Path:
        """Returns the root folder for this race's outputs."""
        return RUNS_ROOT / self.race_id
