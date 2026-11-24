"""Read-only views of a race for people and agents: progress as JSON, and play a build.

`buildoff status [race-id]` summarises each contender from the files the
runner writes (`logs/turns.jsonl`, `logs/cost.csv`, `result.json`), so it works
while a race is running and after it ends, and never touches the race itself.

`buildoff reviews [race-id]` prints every critic round per contender: tier,
Tier 4 claim and checks, the review's own cost and time, notes, and where its
screenshots are.

`buildoff play <race-id> <contender>` serves that contender's latest build
(`workspace/dist/`) on localhost and opens it in the default browser.
"""

import contextlib
import functools
import json
import webbrowser
from pathlib import Path
from typing import Any

from harness.cliutil import CliError
from harness.config import BUILD_DIR, CONTENDERS, RUNS_ROOT
from harness.snapshot import AssetServer, QuietHandler


def race_dir(race_id: str | None) -> Path:
    """The folder of a race id, or of the most recently started race when None.

    Raises:
        CliError: if there is no such race (or no races at all)
    """
    if race_id:
        path = RUNS_ROOT / race_id
        if not (path / "config.json").exists():
            raise CliError(f"no race {race_id!r}", f"races are folders in {RUNS_ROOT}")
        return path
    races = sorted(RUNS_ROOT.glob("*/config.json"), key=lambda p: p.stat().st_mtime)
    if not races:
        raise CliError("no races yet", "start one with `buildoff smoke` or `buildoff race`")
    return races[-1].parent


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Reads a JSON Lines file, or [] if it doesn't exist yet.

    Skips a last line the runner is still writing, so status works mid-race.
    """
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        with contextlib.suppress(json.JSONDecodeError):
            rows.append(json.loads(line))
    return rows


def latest_cost(path: Path) -> float | None:
    """Last spend Nexus reported (cost.csv rows are `elapsed_s,cost_usd`)."""
    if not path.exists():
        return None
    rows = [r for r in path.read_text().splitlines() if r and r[0].isdigit()]
    return float(rows[-1].split(",")[1]) if rows else None


def session_id(logs: Path) -> str | None:
    """The contender's Claude Code session id, from the first transcript event that has one.

    It is what `nexus claude usage --session <id>` takes.
    """
    for transcript in sorted(logs.glob("turn-*.jsonl")):
        with transcript.open() as f:
            for line in f:
                try:
                    event = json.loads(line).get("event") or {}
                except json.JSONDecodeError:
                    continue  # a line still being written
                sid = event.get("session_id") if isinstance(event, dict) else None
                if sid:
                    return str(sid)
    return None


def contender_status(folder: Path) -> dict[str, Any]:
    """One contender's progress: turns recorded, spend, stop reason, where to look.

    Returns:
        a JSON-ready dict; `finished` is true once `result.json` exists
    """
    turns = read_jsonl(folder / "logs" / "turns.jsonl")
    result_path = folder / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    last = turns[-1] if turns else {}
    sid = (result or {}).get("session_id") or session_id(folder / "logs")
    return {
        "finished": result is not None,
        "stop_reason": (result or {}).get("stop_reason"),
        "turns_recorded": max(len(turns) - 1, 0),  # turn 0 is the untouched base game
        "cost_usd": (result or {}).get("cost_usd", latest_cost(folder / "logs" / "cost.csv")),
        "last_turn": {
            k: last.get(k) for k in ("turn", "build_ok", "loaded", "playable", "elapsed_s")
        }
        | {
            "page_errors": len(last.get("page_errors") or []),
            "console_errors": len(last.get("console_errors") or []),
        },
        # Races before prompt-v7 moved DONE.md into logs/ when nudging on, so check both.
        "declared_done": (folder / "workspace" / "DONE.md").exists()
        or any((folder / "logs").glob("done-turn-*.md")),
        "session_id": sid,
        "nexus_meter": f"nexus claude usage --session {sid}" if sid else None,
        "latest_shot": str(max(folder.glob("shots/turn-*.png"), default="")) or None,
        # The critic's tier after each turn, in order (None: no parsed verdict).
        "tiers": [
            r.get("tier") for r in read_jsonl(folder / "logs" / "reviews.jsonl") if "tier" in r
        ],
        "history": f"git --git-dir={folder / 'history.git'} log --oneline",
    }


def status(race_id: str | None) -> dict[str, Any]:
    """Progress of every contender in a race (the latest race when race_id is None)."""
    path = race_dir(race_id)
    config = json.loads((path / "config.json").read_text())
    return {
        "race_id": config["race_id"],
        "budget_usd_per_model": config["budget_usd"],
        "folder": str(path),
        "contenders": {
            c["name"]: contender_status(path / c["name"])
            for c in config["contenders"]
            if (path / c["name"]).exists()
        },
    }


def review_trace(folder: Path) -> list[dict[str, Any]]:
    """Every critic round for one contender, with its Tier 4 check result if one ran.

    `reviews.jsonl` holds a verdict row per round and, when the critic claimed
    Tier 4, a separate `tier4_checks` row for the same turn; this merges them.

    Args:
        folder: the contender's output folder

    Returns:
        one dict per round, oldest first
    """
    rounds: dict[int, dict[str, Any]] = {}
    for row in read_jsonl(folder / "logs" / "reviews.jsonl"):
        entry = rounds.setdefault(row.get("turn", -1), {"turn": row.get("turn")})
        if "tier4_checks" in row:
            entry["tier4_checks"] = row["tier4_checks"]
            continue
        entry |= {
            k: row.get(k)
            for k in (
                "tier",
                "tier4_complete",
                "review_cost_usd",
                "review_seconds",
                "cost_usd",
                "notes",
            )
        }
        shots = row.get("critic_shots") or []
        entry["critic_shots"] = (
            str(folder / "shots" / f"critic-{row.get('turn', 0):03d}") if shots else None
        )
        entry["critic_shot_count"] = len(shots)
    return [rounds[t] for t in sorted(rounds)]


def reviews(race_id: str | None) -> dict[str, Any]:
    """The critic trace of every contender in a race (the latest race when race_id is None)."""
    path = race_dir(race_id)
    config = json.loads((path / "config.json").read_text())
    return {
        "race_id": config["race_id"],
        "contenders": {
            c["name"]: review_trace(path / c["name"])
            for c in config["contenders"]
            if (path / c["name"]).exists()
        },
    }


def play(race_id: str | None, contender: str, port: int, open_browser: bool) -> None:
    """Serves a contender's latest build on localhost until interrupted (Ctrl-C).

    Raises:
        CliError: if the race, contender or build doesn't exist
    """
    names = [c.name for c in CONTENDERS]
    if contender not in names:
        raise CliError(f"no contender {contender!r}", f"one of: {', '.join(names)}")
    site = race_dir(race_id) / contender / "workspace" / BUILD_DIR
    if not (site / "index.html").exists():
        raise CliError(f"no build at {site}", "wait for the contender's first turn to end")
    server = AssetServer(("127.0.0.1", port), functools.partial(QuietHandler, directory=str(site)))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(json.dumps({"url": url, "serving": str(site), "stop": "Ctrl-C"}), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
