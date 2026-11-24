"""The harness's Tier 4 checks (harness.checks) on synthetic frames and shots."""

import os
import time
from pathlib import Path

from PIL import Image, ImageDraw

from harness import checks


def _frame(path: Path, boxes: list[tuple[int, int, int, int]], shade: int = 120) -> Path:
    """Saves a 200x100 grey frame with white boxes drawn at the given spots."""
    img = Image.new("RGB", (200, 100), (shade, shade, shade))
    draw = ImageDraw.Draw(img)
    for box in boxes:
        draw.rectangle(box, fill=(255, 255, 255))
    img.save(path)
    return path


def test_movement_outside_the_player_counts(tmp_path: Path) -> None:
    """A car moving at the edge of the screen registers as a moving city."""
    a = _frame(tmp_path / "a.png", [(0, 40, 20, 60)])
    b = _frame(tmp_path / "b.png", [(25, 40, 45, 60)])
    assert checks.moving_fraction(a, b) > checks.MIN_MOVING_FRACTION


def test_an_idle_player_alone_does_not_count(tmp_path: Path) -> None:
    """Changes only in the middle (the idling player) don't make a city 'move'."""
    a = _frame(tmp_path / "a.png", [(95, 50, 100, 60)])
    b = _frame(tmp_path / "b.png", [(100, 50, 105, 60)])
    assert checks.moving_fraction(a, b) == 0.0


def test_brightness_tells_day_from_night(tmp_path: Path) -> None:
    """A dark frame is dimmer than a light one by more than the required gap."""
    day = _frame(tmp_path / "day.png", [], shade=200)
    night = _frame(tmp_path / "night.png", [], shade=30)
    assert checks.brightness(day) - checks.brightness(night) > checks.MIN_DAY_NIGHT_GAP


def test_critic_shots_must_be_fresh_and_in_tools_shots(tmp_path: Path) -> None:
    """Old shots, missing shots and shots outside tools/shots don't count as evidence."""
    shots = tmp_path / "tools" / "shots"
    shots.mkdir(parents=True)
    started = time.time()
    fresh = _frame(shots / "day.png", [])
    stale = _frame(shots / "old.png", [])
    os.utime(stale, (started - 60, started - 60))
    outside = _frame(tmp_path / "elsewhere.png", [])
    assert checks._own_shot(tmp_path, "tools/shots/day.png", started) == fresh.resolve()
    assert checks._own_shot(tmp_path, "tools/shots/old.png", started) is None
    assert checks._own_shot(tmp_path, str(outside), started) is None
    assert checks._own_shot(tmp_path, "tools/shots/missing.png", started) is None
    assert checks._own_shot(tmp_path, "", started) is None
