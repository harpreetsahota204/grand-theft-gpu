"""Exports the arena's gameplay snapshots and input logs as a COCO4GUI dataset.

The Space stores raw, append-only records (`arena/storage.py`): input event batches
under `events/`, base64 JPEG snapshots under `frames/` and ballots in `votes.jsonl`,
all synced to the private votes dataset. This script joins them on one clock
(`epoch_ms + t_ms`) and writes, per race:

    <out-dir>/<race_id>/images/<sid>/<slot>_<position>.jpg
    <out-dir>/<race_id>/annotations_coco.json   (or annotations_coco_00001.json, ... when
                                                 a race has more than --max-images)

in COCO4GUI format (https://github.com/harpreetsahota204/gui_dataset_creator):

- each snapshot is an `images` entry; one blind play of one build is a sequence
  (`sequence_id` = `<sid>_<slot>`), with the build, contender, vote and input state
  (keys and buttons held, pointer lock, focus) as extra image fields
- each input between the previous snapshot and this one, and each key or button still
  held at capture, is an `annotations` entry; inputs after a play's last snapshot go on
  that snapshot with a negative `ms_before_frame`. Key and look actions span the whole
  frame (the game view is the target); mouse buttons also carry a keypoint at the
  pointer (the screen centre under pointer lock, where first-person games aim)
- ids are derived from the session, slot and capture time, so the same snapshot keeps
  its id across exports and labels made on one export carry over to the next

It streams: shards are indexed by byte offset first, then read one play at a time, so
memory stays bounded by one play plus one output part.

Usage:
    uv run python arena/export_coco4gui.py --repo <ns>/<votes-dataset> --out-dir out
    uv run python arena/export_coco4gui.py --data-dir arena/data/jsonl --out-dir out --race-id ID

Load each part in FiftyOne with the `COCO4GUIDatasetImporter` from that repo, pointing
`data_path` at `images/` and `labels_path` at the part's JSON.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

QUESTIONS: tuple[str, ...] = ("plays_better", "looks_better", "better_main_character", "overall")

# COCO4GUI categories, one per action type the logger can produce.
CATEGORY_NAMES: tuple[str, ...] = (
    "key_down",
    "key_up",
    "key_hold",
    "mouse_down",
    "mouse_up",
    "mouse_hold",
    "look",
)
CATEGORIES: list[dict[str, object]] = [
    {"id": i, "name": name, "supercategory": "interaction"}
    for i, name in enumerate(CATEGORY_NAMES, 1)
]
CATEGORY_ID: dict[str, int] = {name: i for i, name in enumerate(CATEGORY_NAMES, 1)}

MOUSE_BUTTONS: dict[str, str] = {"0": "left", "1": "middle", "2": "right"}

# Half-width of the box drawn around a mouse keypoint, in pixels.
POINT_BOX_HALF_PX: float = 8.0

# Default images per output part: keeps each JSON small enough for FiftyOne to load.
DEFAULT_MAX_IMAGES: int = 50_000

Play = tuple[str, str]  # (sid, slot)
Location = tuple[Path, int]  # (shard, byte offset of the line)


@dataclass
class Event:
    """One input event on the absolute clock."""

    at_ms: float
    kind: str
    code: str


@dataclass
class InputState:
    """What the player is holding and whether the game has their pointer and focus."""

    keys: dict[str, float] = field(default_factory=dict)
    buttons: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    locked: bool = False
    focused: bool = True
    visible: bool = True


@dataclass
class Action:
    """One annotation to write: what happened, to what, and where on the frame."""

    name: str
    element: str
    description: str
    ms_before_frame: int
    locked: bool
    extra: dict[str, object] = field(default_factory=dict)
    point: tuple[float, float] | None = None


@dataclass
class StepChain:
    """Carries the COCO4GUI step chain (`previous_*`, `steps_since_start`) across a play."""

    sequence_id: str
    steps: int = 0
    prev: dict[str, object] | None = None


def stable_id(*parts: object) -> int:
    """Returns a 52-bit id from `parts`, stable across exports and safe as a JS number."""
    digest = hashlib.sha1(":".join(str(p) for p in parts).encode()).hexdigest()
    return int(digest[:13], 16)


def iter_lines(path: Path) -> Iterator[tuple[int, dict[str, object]]]:
    """Yields `(byte_offset, record)` for each parseable JSON object line in `path`."""
    offset = 0
    with path.open("rb") as fh:
        for raw in fh:
            start, offset = offset, offset + len(raw)
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                yield start, rec


def read_at(location: Location) -> dict[str, object]:
    """Reads the JSON record that starts at `location`."""
    path, offset = location
    with path.open("rb") as fh:
        fh.seek(offset)
        return json.loads(fh.readline())


def index_frames(
    data_dir: Path, race_id: str | None
) -> tuple[dict[Play, list[tuple[float, Location]]], dict[Play, str]]:
    """Indexes snapshot lines per play by absolute capture time, without keeping images.

    Returns:
        per play, `(capture_ms, location)` sorted by time; and each play's race id
    """
    frames: dict[Play, list[tuple[float, Location]]] = defaultdict(list)
    races: dict[Play, str] = {}
    for path in sorted((data_dir / "frames").glob("*.jsonl")):
        for offset, rec in iter_lines(path):
            race = str(rec.get("race_id") or "unknown")
            if race_id and race != race_id:
                continue
            play = (str(rec["sid"]), str(rec["slot"]))
            at = float(rec.get("epoch_ms") or 0) + float(rec.get("t_ms") or 0)  # type: ignore[arg-type]
            frames[play].append((at, (path, offset)))
            races[play] = race
    for entries in frames.values():
        entries.sort(key=lambda e: e[0])
    return frames, races


def index_events(data_dir: Path, plays: set[Play]) -> dict[Play, list[tuple[float, Location]]]:
    """Indexes event batches per play (only plays that have snapshots) by arrival time."""
    batches: dict[Play, list[tuple[float, Location]]] = defaultdict(list)
    for path in sorted((data_dir / "events").glob("*.jsonl")):
        for offset, rec in iter_lines(path):
            play = (str(rec.get("sid", "")), str(rec.get("slot", "")))
            if play in plays:
                received = float(rec.get("received_at") or 0.0)  # type: ignore[arg-type]
                batches[play].append((received, (path, offset)))
    for entries in batches.values():
        entries.sort(key=lambda e: e[0])
    return batches


def load_play_events(batches: list[tuple[float, Location]]) -> list[Event]:
    """Reads one play's event batches and returns its events sorted by absolute time.

    Batches written before `epoch_ms` existed fall back to the epoch in the page's last
    `start` event, which is off by only the page's load time.
    """
    events: list[Event] = []
    last_start: float | None = None
    for _, location in batches:
        rec = read_at(location)
        raw = [e for e in rec.get("events") or [] if isinstance(e, list) and len(e) == 3]  # type: ignore[union-attr]
        epoch = rec.get("epoch_ms")
        for t, kind, code in raw:
            if kind == "start":
                try:
                    last_start = float(code) - float(t)
                except (TypeError, ValueError):
                    pass
                if epoch is None:
                    epoch = last_start
        if epoch is None:
            epoch = last_start
        if epoch is None:
            continue
        events.extend(Event(float(epoch) + float(t), str(k), str(c)) for t, k, c in raw)  # type: ignore[arg-type]
    events.sort(key=lambda e: e.at_ms)
    return events


def load_votes(data_dir: Path) -> dict[str, dict[str, str]]:
    """Maps sid -> slot picks (`{question: "a"|"b"|"tie"}`) from `votes.jsonl`."""
    path = data_dir / "votes.jsonl"
    if not path.exists():
        return {}
    return {
        str(rec["sid"]): dict(rec.get("slot_picks") or {})  # type: ignore[arg-type]
        for _, rec in iter_lines(path)
        if "sid" in rec
    }


def parse_point(code: str) -> tuple[str, float, float] | None:
    """Parses a mouse code `button,x,y` (fractions of the viewport); bare buttons give None."""
    parts = code.split(",")
    if len(parts) != 3:
        return None
    try:
        return parts[0], float(parts[1]), float(parts[2])
    except ValueError:
        return None


def apply_event(state: InputState, ev: Event) -> None:
    """Updates the held keys, buttons, pointer lock, focus and visibility for one event."""
    if ev.kind == "kd":
        state.keys.setdefault(ev.code, ev.at_ms)
    elif ev.kind == "ku":
        state.keys.pop(ev.code, None)
    elif ev.kind == "md":
        button, x, y = parse_point(ev.code) or (ev.code, 0.5, 0.5)
        state.buttons[button] = (ev.at_ms, x, y)
    elif ev.kind == "mu":
        point = parse_point(ev.code)
        state.buttons.pop(point[0] if point else ev.code, None)
    elif ev.kind in ("lock", "unlock"):
        state.locked = ev.kind == "lock"
    elif ev.kind in ("focus", "blur"):
        state.focused = ev.kind == "focus"
        if not state.focused:
            # A blurred page stops getting keyup, so treat everything as released.
            state.keys.clear()
            state.buttons.clear()
    elif ev.kind in ("hidden", "visible"):
        state.visible = ev.kind == "visible"
    elif ev.kind in ("start", "exit"):
        state.keys.clear()
        state.buttons.clear()
        state.locked = False


def window_actions(window: list[tuple[Event, bool]], frame_ms: float) -> list[Action]:
    """Turns the inputs since the previous snapshot into actions; mouse moves are summed.

    Args:
        window: each event with whether pointer lock was on when it happened
        frame_ms: absolute time of the snapshot the actions attach to
    """
    actions: list[Action] = []
    look_dx = look_dy = 0
    look_locked = False
    for ev, locked in window:
        ago = round(frame_ms - ev.at_ms)
        verb = "Press" if ev.kind in ("kd", "md") else "Release"
        if ev.kind in ("kd", "ku"):
            name = "key_down" if ev.kind == "kd" else "key_up"
            actions.append(Action(name, ev.code, f"{verb} {ev.code}", ago, locked))
        elif ev.kind in ("md", "mu"):
            button, x, y = parse_point(ev.code) or (ev.code, 0.5, 0.5)
            label = MOUSE_BUTTONS.get(button, button)
            name = "mouse_down" if ev.kind == "md" else "mouse_up"
            description = f"{verb} {label} mouse button"
            actions.append(Action(name, f"mouse_{label}", description, ago, locked, point=(x, y)))
        elif ev.kind == "mv":
            try:
                dx, dy = (int(v) for v in ev.code.split(","))
            except ValueError:
                continue
            look_dx += dx
            look_dy += dy
            look_locked = look_locked or locked
    if look_dx or look_dy:
        description = f"Move the mouse by ({look_dx}, {look_dy}) px"
        extra: dict[str, object] = {"dx": look_dx, "dy": look_dy}
        actions.append(Action("look", "mouse_move", description, 0, look_locked, extra))
    return actions


def hold_actions(state: InputState, frame_ms: float) -> list[Action]:
    """Returns one action per key and mouse button still held at the snapshot."""
    actions = [
        Action(
            "key_hold", code, f"Hold {code}", 0, state.locked, {"held_ms": round(frame_ms - since)}
        )
        for code, since in sorted(state.keys.items())
    ]
    for button, (since, x, y) in sorted(state.buttons.items()):
        label = MOUSE_BUTTONS.get(button, button)
        held: dict[str, object] = {"held_ms": round(frame_ms - since)}
        description = f"Hold {label} mouse button"
        actions.append(
            Action("mouse_hold", f"mouse_{label}", description, 0, state.locked, held, (x, y))
        )
    return actions


def vote_results(picks: dict[str, str] | None, slot: str) -> dict[str, str | None]:
    """Turns one ballot into this slot's result per question: win, loss, tie or None."""
    out: dict[str, str | None] = dict.fromkeys(QUESTIONS)
    for q in QUESTIONS:
        pick = (picks or {}).get(q)
        if pick is not None:
            out[q] = "tie" if pick == "tie" else "win" if pick == slot else "loss"
    return out


def add_annotations(
    annotations: list[dict[str, object]],
    chain: StepChain,
    image: dict[str, object],
    actions: list[Action],
) -> None:
    """Appends COCO4GUI annotations for `actions` on `image`, extending the step chain."""
    width, height = int(image["width"]), int(image["height"])  # type: ignore[call-overload]
    for action in actions:
        chain.steps += 1
        ann_id = stable_id(image["id"], chain.steps)
        ann: dict[str, object] = {
            "id": ann_id,
            "image_id": image["id"],
            "category_id": CATEGORY_ID[action.name],
            "iscrowd": 0,
        }
        if action.point is None:
            # Key and look actions target the whole game view.
            ann["bbox"] = [0, 0, width, height]
            ann["area"] = width * height
        else:
            # Pointer-locked games aim at the screen centre, not the frozen cursor.
            px, py = (0.5, 0.5) if action.locked else action.point
            # Clamp pointer and box strictly inside the image bounds for COCO/FiftyOne.
            cx = max(0.0, min(float(width), px * width))
            cy = max(0.0, min(float(height), py * height))
            half = POINT_BOX_HALF_PX
            box_w = min(2 * half, float(width))
            box_h = min(2 * half, float(height))
            x0 = max(0.0, min(width - box_w, cx - half))
            y0 = max(0.0, min(height - box_h, cy - half))
            ann["bbox"] = [round(x0, 1), round(y0, 1), round(box_w, 1), round(box_h, 1)]
            ann["area"] = round(box_w * box_h, 1)
            ann["keypoints"] = [round(cx, 1), round(cy, 1), 2]
            ann["num_keypoints"] = 1
        prev = chain.prev
        ann["attributes"] = {
            "task_description": action.description,
            "action_type": action.name,
            "element_info": action.element,
            "custom_metadata": {
                "ms_before_frame": action.ms_before_frame,
                "pointer_locked": action.locked,
                **action.extra,
            },
            "sequence_id": chain.sequence_id,
            "sequence_position": image["sequence_position"],
            "previous_annotation_id": prev["id"] if prev else None,
            "previous_step_position": prev["position"] if prev else None,
            "previous_action_type": prev["action_type"] if prev else None,
            "previous_element_type": prev["element"] if prev else None,
            "steps_since_start": chain.steps,
        }
        annotations.append(ann)
        chain.prev = {
            "id": ann_id,
            "position": image["sequence_position"],
            "action_type": action.name,
            "element": action.element,
        }


def export_play(
    images_dir: Path,
    play: Play,
    frames: list[tuple[float, Location]],
    events: list[Event],
    picks: dict[str, str] | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Writes one play's snapshots to disk and returns its COCO4GUI images and annotations."""
    sid, slot = play
    chain = StepChain(f"{sid}_{slot}")
    results = vote_results(picks, slot)
    state = InputState()
    images: list[dict[str, object]] = []
    annotations: list[dict[str, object]] = []
    ev_i = 0
    (images_dir / sid).mkdir(parents=True, exist_ok=True)

    def advance(until_ms: float) -> list[tuple[Event, bool]]:
        """Applies events up to `until_ms` and returns them with the lock state they saw."""
        nonlocal ev_i
        window: list[tuple[Event, bool]] = []
        while ev_i < len(events) and events[ev_i].at_ms <= until_ms:
            window.append((events[ev_i], state.locked))
            apply_event(state, events[ev_i])
            ev_i += 1
        return window

    for position, (at_ms, location) in enumerate(frames, 1):
        rec = read_at(location)
        window = advance(at_ms)
        file_name = f"{sid}/{slot}_{position:05d}.jpg"
        (images_dir / file_name).write_bytes(base64.b64decode(str(rec["jpeg_b64"])))
        image: dict[str, object] = {
            "id": stable_id(sid, slot, at_ms),
            "file_name": file_name,
            "width": int(rec["width"]),  # type: ignore[call-overload]
            "height": int(rec["height"]),  # type: ignore[call-overload]
            "date_captured": datetime.fromtimestamp(at_ms / 1000, UTC).isoformat(),
            "application": "Grand Theft GPU",
            "platform": "web",
            "sequence_id": chain.sequence_id,
            "sequence_position": position,
            "sequence_description": f"Blind play of build {rec.get('build')} as {slot.upper()}",
            "race_id": rec.get("race_id"),
            "sid": sid,
            "slot": slot,
            "build": rec.get("build"),
            "contender": rec.get("contender"),
            "t_ms": rec.get("t_ms"),
            "play_s": rec.get("play_s"),
            "keys_held": sorted(state.keys),
            "buttons_held": sorted(MOUSE_BUTTONS.get(b, b) for b in state.buttons),
            "pointer_locked": state.locked,
            "focused": state.focused,
            "visible": state.visible,
            **{f"vote_{q}": r for q, r in results.items()},
        }
        images.append(image)
        actions = window_actions(window, at_ms) + hold_actions(state, at_ms)
        add_annotations(annotations, chain, image, actions)

    # Inputs after the last snapshot would otherwise vanish from the export.
    trailing = advance(float("inf"))
    if images and trailing:
        add_annotations(annotations, chain, images[-1], window_actions(trailing, frames[-1][0]))
    return images, annotations


def write_part(
    race_dir: Path,
    race: str,
    part: int,
    images: list[dict[str, object]],
    annotations: list[dict[str, object]],
) -> Path:
    """Writes one COCO4GUI JSON part and returns its path."""
    now = datetime.now(UTC)
    coco = {
        "info": {
            "description": f"Grand Theft GPU blind arena gameplay: {race}",
            "version": "1.0",
            "year": now.year,
            "date_created": now.isoformat(),
        },
        "images": images,
        "annotations": annotations,
        "categories": CATEGORIES,
    }
    path = race_dir / f"annotations_coco_{part:05d}.json"
    path.write_text(json.dumps(coco), encoding="utf-8")
    return path


def export(
    data_dir: Path,
    out_dir: Path,
    race_id: str | None = None,
    max_images: int = DEFAULT_MAX_IMAGES,
) -> dict[str, dict[str, int]]:
    """Writes COCO4GUI datasets per race found in `data_dir`, one play at a time.

    Args:
        data_dir: folder laid out like the votes dataset (`votes.jsonl`, `events/`, `frames/`)
        out_dir: destination; each race gets `<out_dir>/<race_id>/`
        race_id: export only this race (default: every race with snapshots)
        max_images: start a new JSON part once a part reaches this many images (plays
            are never split across parts)

    Returns:
        per race, the number of plays, images, annotations and JSON parts written
    """
    frames, races = index_frames(data_dir, race_id)
    batches = index_events(data_dir, set(frames))
    votes = load_votes(data_dir)

    by_race: dict[str, list[Play]] = defaultdict(list)
    for play, race in races.items():
        by_race[race].append(play)

    summary: dict[str, dict[str, int]] = {}
    for race, plays in sorted(by_race.items()):
        race_dir = out_dir / race
        (race_dir / "images").mkdir(parents=True, exist_ok=True)
        # A re-export must not leave stale parts from a run with a different part count.
        for old in race_dir.glob("annotations_coco*.json"):
            old.unlink()
        written: list[Path] = []
        images: list[dict[str, object]] = []
        annotations: list[dict[str, object]] = []
        totals = {"plays": len(plays), "images": 0, "annotations": 0}
        for play in sorted(plays):
            events = load_play_events(batches.get(play, []))
            play_images, play_annotations = export_play(
                race_dir / "images", play, frames[play], events, votes.get(play[0])
            )
            images += play_images
            annotations += play_annotations
            totals["images"] += len(play_images)
            totals["annotations"] += len(play_annotations)
            if len(images) >= max_images:
                written.append(write_part(race_dir, race, len(written) + 1, images, annotations))
                images, annotations = [], []
        if images or not written:
            written.append(write_part(race_dir, race, len(written) + 1, images, annotations))
        if len(written) == 1:
            written[0].rename(race_dir / "annotations_coco.json")
        summary[race] = {**totals, "parts": len(written)}
    return summary


def main() -> None:
    """CLI entry point: optionally downloads the votes dataset, then exports COCO4GUI."""
    parser = argparse.ArgumentParser(description="Export arena snapshots + inputs as COCO4GUI.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--data-dir", type=Path, help="Local copy of the votes dataset")
    src.add_argument("--repo", help="HF dataset repo to download first (uses your HF login)")
    parser.add_argument("--out-dir", type=Path, required=True, help="Where to write the export")
    parser.add_argument("--race-id", help="Export only this race")
    parser.add_argument(
        "--max-images",
        type=int,
        default=DEFAULT_MAX_IMAGES,
        help=f"Images per JSON part (default {DEFAULT_MAX_IMAGES})",
    )
    args = parser.parse_args()

    data_dir = args.data_dir
    if args.repo:
        from huggingface_hub import snapshot_download

        data_dir = Path(
            snapshot_download(
                repo_id=args.repo, repo_type="dataset", local_dir=args.out_dir / "_raw"
            )
        )
    summary = export(data_dir, args.out_dir, args.race_id, args.max_images)
    if not summary:
        print("No snapshots found.")
    for race, n in summary.items():
        print(
            f"{race}: {n['plays']} plays, {n['images']} images, "
            f"{n['annotations']} annotations in {n['parts']} part(s)"
        )


if __name__ == "__main__":
    main()
