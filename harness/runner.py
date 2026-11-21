"""One contender's race: the turn loop, budget watchdog and per-turn evidence.

`harness.race` creates a `ContenderRun` per model and runs them in parallel
threads. Each turn is one headless `claude -p` process. The first turn gets the
spec plus run rules; later turns get the fixed nudge, resuming the same session.
A watchdog polls Nexus (`harness.meter`) during the turn and kills the process
if spend hits the budget or a foreign model shows up in the usage rows.

Output layout under `<race_dir>/<contender>/`:
    workspace/            the seeded Vite project the model builds in (a git repo)
    logs/turn-NNN.jsonl   timestamped Claude Code stream-json transcript per turn
    logs/cost.csv         timestamped Nexus spend readings
    logs/turns.jsonl      one row per turn (turn 0 = seeded base): build, load, errors
    logs/events.jsonl     harness events: cross-model leak, unpriced rows (absent if none)
    shots/turn-NNN.png    screenshot of the built game after each turn (000 = base)
    result.json           final outcome
"""

import contextlib
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Literal, TextIO

from harness import meter, seed, snapshot
from harness.config import (
    BUILD_DIR,
    DONE_FILE,
    MAX_NUDGES,
    METER_POLL_SECONDS,
    PROMPTS_DIR,
    TOOLS,
    Contender,
    RaceConfig,
)

StopReason = Literal["declared_done", "nudge_cap", "budget", "leak", "error"]
TurnEnd = Literal["completed", "budget", "leak", "error"]

# An empty MCP config plus --strict-mcp-config removes the user's connectors
# (Notion, Gmail, ...) from the race sessions.
EMPTY_MCP: str = '{"mcpServers":{}}'


@dataclass
class RunResult:
    """Final outcome of one contender's race, written to result.json.

    Attributes:
        contender: contender name
        session_id: Claude Code session UUID, usable with `nexus claude usage`
        stop_reason: why the run ended
        turns: number of `claude -p` invocations
        nudges: how many of those were nudges
        cost_usd: final spend per Nexus
        wall_seconds: total elapsed time
        first_playable_turn: first turn whose build loaded without errors, if any
        first_playable_seconds: elapsed seconds at the end of that turn
        models_seen: every model Nexus logged for this session
    """

    contender: str
    session_id: str
    stop_reason: StopReason
    turns: int
    nudges: int
    cost_usd: float
    wall_seconds: float
    first_playable_turn: int | None
    first_playable_seconds: float | None
    models_seen: list[str]


class ContenderRun:
    """Drives one model through the race.

    Created by `harness.race` with the shared `RaceConfig`; `run()` blocks until
    the contender stops and returns its `RunResult`. Safe to run two instances in
    parallel threads: they share no state and use separate folders and sessions.

    Attributes:
        contender: which model this run drives
        cfg: race-wide settings
        root: this contender's output folder
        session_id: fixed UUID so Nexus can be queried mid-turn
    """

    def __init__(self, contender: Contender, cfg: RaceConfig) -> None:
        """Sets up paths and a fresh session ID; touches nothing on disk yet."""
        self.contender = contender
        self.cfg = cfg
        self.root: Path = cfg.race_dir / contender.name
        self.workspace: Path = self.root / "workspace"
        self.logs: Path = self.root / "logs"
        self.shots: Path = self.root / "shots"
        self.session_id: str = str(uuid.uuid4())
        self._last: meter.Reading | None = None
        self._start: float = 0.0
        # Highest unpriced-row count already logged as a warning event.
        self._unpriced_seen: int = 0

    def run(self) -> RunResult:
        """Runs turns until done, nudge cap, budget or leak, then writes result.json.

        Returns:
            the contender's final result
        """
        # Seeding happens before the clock starts: npm install and copying the
        # base game aren't the model's time.
        seed.seed_workspace(self.workspace)
        snapshot.init_workspace(self.workspace)
        self.logs.mkdir(parents=True, exist_ok=True)
        # Turn 0 is the untouched base game: the "before" frame for the video
        # and the diff base for scoring.
        self._record_turn(0, "seed")
        self._start = time.monotonic()

        prompt = build_first_prompt(self.cfg.spec_path)
        nudge = (PROMPTS_DIR / "nudge.md").read_text()
        turn = nudges = 0
        first_playable: tuple[int, float] | None = None

        while True:
            turn += 1
            end = self._run_turn(prompt, turn)

            # Evidence after every turn, including the one the watchdog killed,
            # so the final state of the build is always captured.
            playable = self._record_turn(turn, end)
            if first_playable is None and playable:
                first_playable = (turn, time.monotonic() - self._start)

            reason = self._stop_reason(end, nudges)
            if reason is not None:
                break

            nudges += 1
            prompt = nudge

        result = RunResult(
            contender=self.contender.name,
            session_id=self.session_id,
            stop_reason=reason,
            turns=turn,
            nudges=nudges,
            cost_usd=self._cost(),
            wall_seconds=round(time.monotonic() - self._start, 1),
            first_playable_turn=first_playable[0] if first_playable else None,
            first_playable_seconds=round(first_playable[1], 1) if first_playable else None,
            models_seen=sorted(self._last.models) if self._last else [],
        )
        (self.root / "result.json").write_text(json.dumps(asdict(result), indent=2))
        return result

    def _record_turn(self, turn: int, end: TurnEnd | Literal["seed"]) -> bool:
        """Commits, builds and screenshots the workspace, and logs a turns.jsonl row.

        Args:
            turn: turn number; 0 is the seeded base game before any model work
            end: how the turn ended, or "seed" for turn 0

        Returns:
            whether this turn's game is playable: it built, loaded, and logged
            no console errors
        """
        message = f"turn {turn}" if turn else "seed: base game + assets"
        sha = snapshot.commit(self.workspace, message)
        built = snapshot.build(self.workspace)
        shot = (
            snapshot.screenshot(self.workspace / BUILD_DIR, self.shots / f"turn-{turn:03d}.png")
            if built.ok
            else snapshot.ShotResult(has_entry=False, loaded=False, console_errors=[])
        )
        self._append_jsonl(
            "turns.jsonl",
            {
                "turn": turn,
                "end": end,
                "commit": sha,
                # Turn 0 is recorded before the race clock starts.
                "elapsed_s": round(time.monotonic() - self._start, 1) if turn else 0.0,
                "cost_usd": self._cost(),
                "build_ok": built.ok,
                "build_log_tail": built.log_tail,
                "has_entry": shot.has_entry,
                "loaded": shot.loaded,
                "console_errors": shot.console_errors[:20],
            },
        )
        return built.ok and shot.loaded and not shot.console_errors

    def _stop_reason(self, end: TurnEnd, nudges: int) -> StopReason | None:
        """Applies the stop rules after a turn, in priority order.

        Hard limits first (budget, leak, error), then the model's own call
        (DONE.md exists), then the nudge cap.

        Args:
            end: how the turn that just finished ended
            nudges: nudges sent so far

        Returns:
            why the run should stop, or None to send another nudge
        """
        if end != "completed":
            return end
        if (self.workspace / DONE_FILE).exists():
            return "declared_done"
        if nudges >= MAX_NUDGES:
            return "nudge_cap"
        return None

    def _run_turn(self, prompt: str, turn: int) -> TurnEnd:
        """Runs one `claude -p` process under the budget/leak watchdog.

        Args:
            prompt: spec (turn 1) or the fixed nudge (later turns)
            turn: 1-based turn number, used for the log filename

        Returns:
            how the turn ended
        """
        log_path = self.logs / f"turn-{turn:03d}.jsonl"
        env = {**os.environ, "CLAUDE_CODE_SUBAGENT_MODEL": self.contender.model}

        verdict: TurnEnd | None = None
        with log_path.open("w") as log:
            # start_new_session puts claude and every shell it spawns in one
            # process group, so a budget kill takes down the whole tree.
            proc = subprocess.Popen(
                self._claude_cmd(prompt, first=turn == 1),
                cwd=self.workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            # A reader thread drains the pipe while this thread runs the watchdog;
            # without it a full pipe buffer would stall claude.
            pump = threading.Thread(target=self._pump, args=(proc.stdout, log), daemon=True)
            pump.start()
            while True:
                try:
                    proc.wait(timeout=METER_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                verdict = self._check_meter()
                if verdict is not None:
                    _kill_tree(proc)
                    break
            # Let the pump flush the tail of the output before the log closes.
            pump.join(timeout=10)

        # If claude exited on its own, take one more reading: the last requests of
        # the turn land after the final mid-turn poll.
        if verdict is None:
            verdict = self._check_meter()
        if verdict is not None:
            return verdict
        return "completed" if proc.returncode == 0 else "error"

    def _pump(self, stream: IO[bytes], log: TextIO) -> None:
        """Copies claude's output into the turn log, stamping each line with race time.

        Each log row is `{"t": seconds_since_race_start, "event": <stream-json obj>}`,
        or `{"t": ..., "raw": text}` for non-JSON lines (stderr). The timestamps
        let the video be rendered from logs later, in sync across contenders.

        Args:
            stream: claude's combined stdout/stderr pipe
            log: open turn log file
        """
        for raw in stream:
            t = round(time.monotonic() - self._start, 2)
            text = raw.decode("utf-8", errors="replace").rstrip("\n")
            try:
                row: dict[str, object] = {"t": t, "event": json.loads(text)}
            except json.JSONDecodeError:
                row = {"t": t, "raw": text}
            log.write(json.dumps(row) + "\n")
            # Flush per line so the live viewer sees events as they happen.
            log.flush()

    def _claude_cmd(self, prompt: str, first: bool) -> list[str]:
        """Builds the Claude Code command line for one turn.

        Both contenders get identical flags; only `--model` differs.

        Args:
            prompt: text for this turn
            first: True to start the session, False to resume it

        Returns:
            argv for subprocess
        """
        session = ["--session-id", self.session_id] if first else ["--resume", self.session_id]
        return [
            "claude",
            "-p",
            prompt,
            "--model",
            self.contender.model,
            *session,
            # Unattended run: tools are pre-approved instead of prompting.
            "--permission-mode",
            "acceptEdits",
            "--tools",
            ",".join(TOOLS),
            "--allowed-tools",
            ",".join(TOOLS),
            # Isolation from the user's own Claude Code setup.
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--mcp-config",
            EMPTY_MCP,
            # stream-json needs --verbose in print mode; it gives the live viewer
            # every message and tool call as it happens.
            "--output-format",
            "stream-json",
            "--verbose",
        ]

    def _check_meter(self) -> TurnEnd | None:
        """Polls Nexus, logs the reading, and says whether the turn must stop.

        Also writes an `unpriced` warning to events.jsonl when Nexus reports
        rows it couldn't price (spend undercounted); that never stops the turn.

        Returns:
            "leak" if a model other than the contender's appears, "budget" if
            spend reached the cap, otherwise None
        """
        reading = meter.read_session(self.session_id)
        if reading is None:
            return None
        self._last = reading
        with (self.logs / "cost.csv").open("a") as f:
            f.write(f"{time.monotonic() - self._start:.1f},{reading.cost_usd:.6f}\n")

        # Unpriced rows mean spend is undercounted. Warn but keep racing; only log
        # when the count grows so a stuck row doesn't add a line every poll.
        if reading.unpriced > self._unpriced_seen:
            self._unpriced_seen = reading.unpriced
            self._append_jsonl(
                "events.jsonl",
                {"event": "unpriced", "rows": reading.unpriced, "cost_usd": reading.cost_usd},
            )

        foreign = reading.models - {self.contender.nexus_model}
        if foreign:
            self._append_jsonl("events.jsonl", {"event": "leak", "models": sorted(foreign)})
            return "leak"
        if reading.cost_usd >= self.cfg.budget_usd:
            return "budget"
        return None

    def _cost(self) -> float:
        """Returns the latest Nexus spend in USD, or 0.0 before the first reading."""
        return round(self._last.cost_usd, 6) if self._last else 0.0

    def _append_jsonl(self, name: str, row: dict[str, object]) -> None:
        """Appends one JSON row to a file in this contender's logs folder."""
        with (self.logs / name).open("a") as f:
            f.write(json.dumps(row) + "\n")


def build_first_prompt(spec_path: Path) -> str:
    """Joins the game spec with the run rules both models must follow.

    The rules (entry file, DONE.md) are kept out of the spec so the spec reads as
    a pure game brief and the harness contract lives in one file.

    Args:
        spec_path: markdown game spec

    Returns:
        the full first-turn prompt
    """
    rules = (PROMPTS_DIR / "run_rules.md").read_text()
    return f"{spec_path.read_text().strip()}\n\n{rules.strip()}\n"


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stops a claude process and everything it spawned.

    Sends SIGTERM to the process group, then SIGKILL if it hasn't exited within
    10 seconds.

    Args:
        proc: a process started with start_new_session=True
    """
    # start_new_session makes claude a group leader, so its PID is the group ID.
    # Using it directly (not os.getpgid) still works if claude itself already
    # exited between the last poll and this kill but its children didn't.
    pgid = proc.pid
    # The whole group can also be gone already; that's the outcome we wanted.
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait()
