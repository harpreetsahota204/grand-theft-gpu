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

# A turn that produces no transcript output and no new spend for this long is
# killed and recorded as "stalled", then the model is nudged to continue. In a
# dry run, a model ran `npm run preview` (a server that never exits) in the
# foreground and sat blocked for 35 minutes. Generous enough for long installs.
STALL_TIMEOUT_S: float = 600.0

# Contract files the run rules tell each model about. The game is a Vite
# project: the harness builds it each turn and loads BUILD_DIR/GAME_ENTRY.
DONE_FILE: str = "DONE.md"
BUILD_DIR: str = "dist"
GAME_ENTRY: str = "index.html"

# The base game both contenders start from, pinned so every race starts from
# identical code. Fetched at seed time (not vendored); the link is the attribution.
BASE_REPO_URL: str = "https://github.com/kartik786-git/gta-clone-threejs.git"
BASE_REPO_COMMIT: str = "babb6232df0f50d92e66a4b994a5fbc14fcc37d9"

# Our asset pack and where the prompt promises it inside each workspace.
# Vite serves public/ at the site root, so the game loads /assets/gt-gpu/...
ASSETS_DIR: Path = REPO_ROOT / "assets"

# Local staging copy of the Hugging Face asset dataset
# (harpreetsahota/grand-theft-gpu-assets). `buildoff assets mirror` downloads
# the third-party sets in scripts/mirror_sources.json here, outside the repo.
MIRROR_DIR: Path = Path.home() / "grand-theft-gpu-assets"

# The published asset dataset and the exact revision races use. Seeding and
# `buildoff assets fetch` download this revision, so every race gets identical
# files; bump it deliberately after re-publishing (it changes what races see).
HF_ASSETS_REPO: str = "harpreetsahota/grand-theft-gpu-assets"
HF_ASSETS_REVISION: str = "717f91bbc3755ac942fd0afbbbc657826be126cc"

# Blender runs the USDCraft converter; $BLENDER overrides this macOS default.
DEFAULT_BLENDER: str = "/Applications/Blender.app/Contents/MacOS/Blender"
GAME_ASSETS_SUBDIR: str = "public/assets/gt-gpu"

# How long the game gets to finish loading after the network goes quiet, in ms.
# The base game needs ~9 s headless (models are parsed between downloads).
SCREENSHOT_SETTLE_MS: int = 12000


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
        pack: seeded assets, "full" or "primitives" (see `harness.fetch.PACK_PATTERNS`)
        nudge_on_done: True = a DONE.md before the last nudge is set aside and the
            model nudged on (races); False = DONE.md ends the run (smoke test)
        contenders: who races
    """

    spec_path: Path
    budget_usd: float
    race_id: str
    open_viewers: bool = True
    pack: str = "full"
    nudge_on_done: bool = True
    contenders: tuple[Contender, ...] = CONTENDERS

    @property
    def race_dir(self) -> Path:
        """Returns the root folder for this race's outputs."""
        return RUNS_ROOT / self.race_id
