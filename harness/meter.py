"""Spend and model identity for a Claude Code session, as reported by Nexus.

Nexus is the referee: Claude Code misprices models it doesn't know (it billed a
Kimi call at 2x list), while `nexus claude usage --json` prices every row at
Fireworks/Anthropic list rates and includes subagents. `harness.runner` polls
`read_session` during each turn to enforce the budget and catch leaks.
"""

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reading:
    """One snapshot of a session's usage.

    Attributes:
        cost_usd: total spend in USD, parent plus subagents, at list price
        models: every `displayModel` seen in parent and subagent rows
        unpriced: rows Nexus could not price; nonzero means cost is understated
    """

    cost_usd: float
    models: frozenset[str]
    unpriced: int


def read_session(session_id: str) -> Reading | None:
    """Reads current usage for one Claude Code session from Nexus.

    Never raises: any failure (Nexus missing, hung, logged out, unexpected JSON)
    returns None. The runner treats a long run of Nones as a dead meter and
    stops the turn (`config.METER_BLIND_LIMIT_S`), so this fails closed.

    Args:
        session_id: the UUID passed to Claude Code via `--session-id`

    Returns:
        the reading, or None if Nexus has nothing yet (the session transcript is
        written a few seconds after the process starts) or couldn't be read
    """
    try:
        proc = subprocess.run(
            ["nexus", "claude", "usage", "--session", session_id, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    # A missing transcript shows up as a nonzero exit or non-JSON output, not a
    # zero-cost reading, so callers can tell "nothing yet" from "$0".
    if proc.returncode != 0:
        return None
    try:
        return parse_usage(json.loads(proc.stdout))
    except (ValueError, KeyError, TypeError, AttributeError):  # AttributeError: not a dict
        return None


def parse_usage(data: dict[str, Any]) -> Reading:
    """Turns `nexus claude usage --json` output into a Reading.

    Raises:
        KeyError, TypeError, ValueError: if the JSON isn't the expected shape
    """
    # Subagent rows are listed separately; fold them in so the leak check
    # covers every model call the session made.
    models = {row["displayModel"] for row in data.get("rows", [])}
    for sub in data.get("subagents", []):
        models |= {row["displayModel"] for row in sub.get("rows", [])}

    return Reading(
        cost_usd=float(data["grandTotals"]["cost"]),
        models=frozenset(models),
        unpriced=int(data.get("unpriced", 0)),
    )
