"""The harness's own Tier 4 checks, run when a contender's critic says Tier 4.

`harness.runner` ends a run as `tier4` only when the critic (`prompts/critic.md`)
judges the game complete AND these checks pass, so a critic can't wave its
own builder through on words alone:

1. **The build is playable** (built, loaded, rendered, no uncaught exception).
2. **The city moves on its own.** Two frames of the built game, a few seconds
   apart with no input, must differ outside the middle of the screen, where an
   idle player character stands. Traffic and pedestrians cause that; a frozen
   city doesn't.
3. **Day and night look different.** The critic must name a daylight and a
   night screenshot it took this round; the night one must be clearly darker.

These are necessary, not sufficient: they catch a missing or frozen feature,
not a poor one. Judging quality is the critic's job, and the blind judging's
after the race.
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops

from harness import snapshot
from harness.config import BUILD_DIR

# A pixel counts as changed when any channel moves by more than this (0-255),
# which ignores compression and dithering noise.
PIXEL_DELTA: int = 24
# Fraction of the outer screen that must change between the two frames.
MIN_MOVING_FRACTION: float = 0.01
MOTION_GAP_MS: int = 3000
# The middle of the frame, where a third-person player idles (breathing and
# idle animations move it even in an empty world), as fractions of width/height.
PLAYER_BOX: tuple[float, float, float, float] = (0.35, 0.25, 0.65, 0.85)
# Mean brightness (0-1) the day shot must exceed the night shot by.
MIN_DAY_NIGHT_GAP: float = 0.12


@dataclass(frozen=True)
class CheckResult:
    """Outcome of the Tier 4 checks.

    Attributes:
        passed: every check passed
        failures: one plain sentence per failed check, sent to the builder
        details: the measured numbers, for the logs
    """

    passed: bool
    failures: list[str] = field(default_factory=list)
    details: dict[str, object] = field(default_factory=dict)


def moving_fraction(first: Path, second: Path) -> float:
    """Fraction of pixels outside PLAYER_BOX that changed between two frames."""
    a = Image.open(first).convert("RGB")
    b = Image.open(second).convert("RGB").resize(a.size)
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > PIXEL_DELTA else 0)
    w, h = diff.size
    box = (
        int(PLAYER_BOX[0] * w),
        int(PLAYER_BOX[1] * h),
        int(PLAYER_BOX[2] * w),
        int(PLAYER_BOX[3] * h),
    )
    # Blank out the player's area, then count what changed everywhere else.
    diff.paste(0, box)
    outer = w * h - (box[2] - box[0]) * (box[3] - box[1])
    # After the threshold every pixel is 0 or 255, so the histogram's last bin counts changes.
    changed = diff.histogram()[255]
    return changed / outer if outer else 0.0


def brightness(png: Path) -> float:
    """Mean brightness of an image, 0 (black) to 1 (white)."""
    hist = Image.open(png).convert("L").histogram()
    count = sum(hist)
    return sum(level * n for level, n in enumerate(hist)) / (255 * count) if count else 0.0


def _own_shot(workspace: Path, path: str, since: float) -> Path | None:
    """Resolves a critic-named screenshot, or None if it's missing, stale or outside tools/shots."""
    if not path:
        return None
    shot = (workspace / path).resolve() if not Path(path).is_absolute() else Path(path)
    shots_dir = (workspace / "tools" / "shots").resolve()
    if not shot.is_relative_to(shots_dir) or not shot.is_file():
        return None
    return shot if shot.stat().st_mtime >= since else None


def tier4(
    workspace: Path, out_dir: Path, day_shot: str, night_shot: str, critic_started: float
) -> CheckResult:
    """Runs the three Tier 4 checks on the current build.

    Args:
        workspace: the contender's game folder (already built into dist/)
        out_dir: where to save the probe frames (outside the workspace)
        day_shot: the critic's daylight screenshot path
        night_shot: the critic's night screenshot path
        critic_started: wall-clock time the critic began; older shots don't count

    Returns:
        whether all checks passed, with a sentence per failure
    """
    failures: list[str] = []
    details: dict[str, object] = {}

    # 1 and 2: one page load gives the playability verdict and two frames.
    first, second = out_dir / "motion-0.png", out_dir / "motion-1.png"
    shot = snapshot.screenshot(workspace / BUILD_DIR, first, later=[(MOTION_GAP_MS, second)])
    details["playable"] = shot.playable
    if not shot.playable:
        failures.append("The built game doesn't load and render without errors.")
    else:
        moving = moving_fraction(first, second)
        details["moving_fraction"] = round(moving, 4)
        if moving < MIN_MOVING_FRACTION:
            failures.append(
                "With no input, nothing on screen moves: the city looks frozen "
                "(no traffic or pedestrians in view)."
            )

    # 3: the critic's own day and night evidence.
    day = _own_shot(workspace, day_shot, critic_started)
    night = _own_shot(workspace, night_shot, critic_started)
    if day is None or night is None:
        failures.append(
            "There's no daylight and night screenshot from this review to show the day/night cycle."
        )
    else:
        gap = brightness(day) - brightness(night)
        details["day_night_gap"] = round(gap, 3)
        if gap < MIN_DAY_NIGHT_GAP:
            failures.append("The night screenshot isn't clearly darker than the daylight one.")

    return CheckResult(passed=not failures, failures=failures, details=details)
