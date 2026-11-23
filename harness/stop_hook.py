"""Claude Code Stop hook: keeps a model working when it stops without finishing.

`harness.session` registers this module as a command-type Stop hook in each
contender's `--settings` file, identically for both sides. Claude Code runs it
(inside the contender's sandbox) whenever the model tries to end its turn,
passing the hook input as JSON on stdin. It blocks the stop, with the locked
nudge text as the reason, in two cases:

1. The model's last message announces work it is about to do ("I'm adding
   browser checks now…") and DONE.md doesn't exist. In the dry runs this ended
   whole turns, each one costing a nudge.
2. DONE.md doesn't exist and the game doesn't build. A turn shouldn't end on a
   broken build without the model being told to keep going.

Otherwise the stop goes ahead and the harness's normal turn/nudge rules apply.
Claude Code itself ends the turn after 8 consecutive blocks with no tool call
in between, so a model that keeps replying without acting can't loop forever.
The decision is deterministic and the reason text is the same fixed nudge the
models already get between turns, so the hook adds no new instructions.

Usage (set up by `harness.session.write`):
    python -m harness.stop_hook <nudge.txt>     # hook input JSON on stdin
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# config.py is in the toolkit too, so the hook reads the same DONE.md name the runner does.
from harness.config import DONE_FILE

# How much of the end of the last message to inspect: the announcement that
# ends a turn early is the closing sentence, not something said earlier.
TAIL_CHARS: int = 400
# A Vite build takes seconds; this stays under the hook's own 180 s limit
# (session.STOP_HOOK_TIMEOUT_S) so a hung build reads as a failure, not a timeout.
BUILD_TIMEOUT_S: int = 150

# First-person statements of work about to happen. Matched case-insensitively
# on the message tail, after curly apostrophes are straightened (Kimi writes
# "I’m"). Past-tense summaries ("I added…", "I've built…") don't match.
ANNOUNCES_WORK: re.Pattern[str] = re.compile(
    r"\b(?:i'll|i will|i'm going to|i am going to|let me|next,? i|now i|i'm now|"
    r"i'm (?:adding|writing|implementing|fixing|creating|running|building|updating|"
    r"testing|checking|wiring|starting|working))\b",
    re.IGNORECASE,
)


def announces_work(message: str) -> bool:
    """True if the message ends by announcing work instead of reporting it."""
    tail = message[-TAIL_CHARS:].replace("’", "'")
    return bool(ANNOUNCES_WORK.search(tail))


def builds(workspace: Path) -> bool:
    """True if `npm run build` succeeds in the workspace (within BUILD_TIMEOUT_S)."""
    try:
        proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=workspace,
            capture_output=True,
            timeout=BUILD_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def decide(payload: dict[str, object], workspace: Path) -> bool:
    """Whether to block this stop.

    Args:
        payload: Claude Code's Stop hook input (`last_assistant_message`, ...)
        workspace: the game folder (the hook's working directory)

    Returns:
        True to block the stop and keep the model working
    """
    if (workspace / DONE_FILE).exists():
        return False
    if announces_work(str(payload.get("last_assistant_message") or "")):
        return True
    return not builds(workspace)


def main() -> None:
    """Reads the hook input, prints a block decision if needed, and always exits 0."""
    nudge = Path(sys.argv[1]).read_text().strip()
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return  # never break the model's turn over a malformed hook input
    workspace = Path(str(payload.get("cwd") or ".")).resolve()
    if decide(payload, workspace):
        print(json.dumps({"decision": "block", "reason": nudge}))


if __name__ == "__main__":
    main()
