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

# The critic (a fresh session of the same model, see harness.runner) only plays
# and reads the game: no editing tools, and a read-only sandbox besides.
CRITIC_TOOLS: tuple[str, ...] = ("Bash", "Read")
# Provider API errors (e.g. a dropped stream) are retried by resuming the session
# with the nudge, up to this many times per run, without using up the model's
# reviews: an infrastructure hiccup shouldn't end or shorten a model's race.
MAX_API_RETRIES: int = 3

# How often the watchdog asks Nexus for spend during a turn. Subagents can burn a
# few dollars between polls, so expect final spend slightly over budget.
METER_POLL_SECONDS: float = 15.0

# A turn that produces no transcript output and no new spend for this long is
# killed and recorded as "stalled", then the model is nudged to continue. In a
# dry run, a model ran `npm run preview` (a server that never exits) in the
# foreground and sat blocked for 35 minutes. Generous enough for long installs.
STALL_TIMEOUT_S: float = 600.0

# The meter is the only thing enforcing the budget, so it fails closed: if Nexus
# gives no reading for this long during a turn (down, logged out, bad JSON), the
# turn is killed and the run stops as "meter_down" rather than spending blind.
# Long enough to cover the few seconds before a new session's first reading.
METER_BLIND_LIMIT_S: float = 180.0

# Same reasoning effort and compaction point on both sides (harness.session),
# instead of each model's own default. "max" is what Moonshot evaluates Kimi
# K3.1 at; compaction at 1M tokens is the context window Claude Code reports
# for both models.
EFFORT_LEVEL: str = "max"
AUTO_COMPACT_WINDOW: str = "1000000"

# Environment variables passed through to each `claude` process. Everything else
# (API keys, tokens, the parent Claude Code session's variables) is dropped, so a
# model's Bash can't read the user's secrets from its environment. Nexus routing
# and auth live in ~/.claude/settings.json, which Claude Code reads itself.
ENV_ALLOWLIST: tuple[str, ...] = (
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "__CF_USER_TEXT_ENCODING",
)

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
    # Both pinned by full ID, so an alias update can't swap models mid-race.
    # (`kimi-latest` also made Claude Code log "unrecognized model" every turn;
    # the pinned ID is recognised, with its 1M context window.)
    Contender(name="kimi", model="kimi-k3p1-pro", nexus_model="kimi-k3p1-pro"),
    Contender(name="opus", model="claude-opus-5-5", nexus_model="claude-opus-5-5"),
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
        stop_on_done: True = the first DONE.md ends the run, after one review
            (smoke test); False = only Tier 4 verified or the budget ends it (races)
        contenders: who races
    """

    spec_path: Path
    budget_usd: float
    race_id: str
    open_viewers: bool = True
    pack: str = "full"
    stop_on_done: bool = False
    contenders: tuple[Contender, ...] = CONTENDERS

    @property
    def race_dir(self) -> Path:
        """Returns the root folder for this race's outputs."""
        return RUNS_ROOT / self.race_id
