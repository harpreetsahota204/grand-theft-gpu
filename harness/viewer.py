"""Live terminal view of one contender: what the model says and does, plus spend.

`harness.race` opens one Terminal window per contender running
`python -m harness.viewer <contender_dir>` so you can watch the race live. The
viewer only reads files the runner writes, so it can be
started, closed or restarted at any time without affecting the race.
"""

import json
import sys
import time
from pathlib import Path

# ANSI colors for the three kinds of lines the viewer prints.
DIM, CYAN, YELLOW, RESET = "\033[2m", "\033[36m", "\033[33m", "\033[0m"
TEXT_PREVIEW_CHARS: int = 300
POLL_SECONDS: float = 0.5


def main(contender_dir: Path) -> None:
    """Follows every turn log for a contender, in order, forever.

    Args:
        contender_dir: `<race_dir>/<contender>` as written by `harness.runner`
    """
    logs = contender_dir / "logs"
    print(f"{YELLOW}== {contender_dir.name} =={RESET}", flush=True)
    turn = 1
    while True:
        log = logs / f"turn-{turn:03d}.jsonl"
        if not log.exists():
            time.sleep(POLL_SECONDS)
            continue
        print(f"{YELLOW}-- turn {turn} --{RESET}", flush=True)
        _follow(log, logs / f"turn-{turn + 1:03d}.jsonl", logs / "cost.csv")
        turn += 1


def _follow(log: Path, next_log: Path, cost_csv: Path) -> None:
    """Prints events from one turn log until the next turn's log appears.

    Args:
        log: the turn's stream-json transcript
        next_log: path whose existence means this turn is over
        cost_csv: Nexus spend readings, shown after each tool call
    """
    with log.open() as f:
        buf = ""
        while True:
            chunk = f.readline()
            if chunk:
                # Lines can arrive partially written; only parse complete ones.
                buf += chunk
                if buf.endswith("\n"):
                    _render(buf, cost_csv)
                    buf = ""
                continue
            if next_log.exists():
                return
            time.sleep(POLL_SECONDS)


def _render(line: str, cost_csv: Path) -> None:
    """Prints one stream-json event as a short human-readable line.

    Args:
        line: one runner log row, `{"t": ..., "event": <stream-json obj>}`
        cost_csv: Nexus spend readings, for the running total
    """
    try:
        event = json.loads(line).get("event") or {}
    except json.JSONDecodeError:
        return
    if event.get("type") != "assistant":
        return
    for block in event.get("message", {}).get("content", []):
        if block.get("type") == "text" and block["text"].strip():
            print(block["text"].strip()[:TEXT_PREVIEW_CHARS], flush=True)
        elif block.get("type") == "tool_use":
            args = json.dumps(block.get("input", {}))[:120]
            print(f"{CYAN}> {block['name']}{RESET} {DIM}{args}{RESET}", flush=True)
            print(f"{DIM}  spent ${_latest_cost(cost_csv):.2f}{RESET}", flush=True)


def _latest_cost(cost_csv: Path) -> float:
    """Returns the most recent Nexus spend reading in USD, or 0.0 if none yet."""
    if not cost_csv.exists():
        return 0.0
    lines = cost_csv.read_text().strip().splitlines()
    return float(lines[-1].split(",")[1]) if lines else 0.0


if __name__ == "__main__":
    main(Path(sys.argv[1]))
