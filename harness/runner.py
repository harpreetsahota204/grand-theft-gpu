"""One contender's race: the turn loop, budget watchdog and per-turn evidence.

`harness.race` creates a `ContenderRun` per model and runs them in parallel
threads. Each turn is one headless `claude -p` process. The first turn gets the
spec plus run rules; later turns get the fixed nudge, resuming the same session.
A watchdog polls Nexus (`harness.meter`) during the turn and kills the process
if spend hits the budget, a foreign model shows up in the usage rows, or the
turn stalls (no output and no new spend for STALL_TIMEOUT_S). After each turn,
any server the model left running in its workspace is stopped.

Declaring done doesn't end the run while nudges remain: DONE.md is moved to
`logs/done-turn-NNN.md` (the turn's commit still has it) and the model gets
the fixed nudge, so both models are pushed toward the full budget the same way.

Output layout under `<race_dir>/<contender>/`:
    workspace/            the seeded Vite project the model builds in (a git repo)
    logs/turn-NNN.jsonl   timestamped Claude Code stream-json transcript per turn
    logs/cost.csv         timestamped Nexus spend readings
    logs/turns.jsonl      one row per turn (turn 0 = seeded base): build, load, errors
    logs/events.jsonl     harness events: leak, stalled turn, unpriced rows (absent if none)
    logs/done-turn-NNN.md each DONE.md the model wrote before its last nudge
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
    MAX_API_RETRIES,
    MAX_NUDGES,
    METER_POLL_SECONDS,
    PROMPTS_DIR,
    STALL_TIMEOUT_S,
    TOOLS,
    Contender,
    RaceConfig,
)

StopReason = Literal["declared_done", "nudge_cap", "budget", "leak", "error"]
TurnEnd = Literal["completed", "stalled", "budget", "leak", "error", "api_error"]
# Claude Code's final message when the provider API fails mid-turn, e.g.
# "API Error: The response stopped arriving."
API_ERROR_PREFIX: str = "API Error"

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
        done_declared: each time the model wrote DONE.md: turn and spend so far
        api_retries: turns resumed after a provider API error (not counted as nudges)
        pack: which asset pack the workspace was seeded with
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
    done_declared: list[dict[str, float]]
    api_retries: int
    pack: str


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
        # Last time the turn showed life (new output line or new spend); the
        # watchdog kills a turn that stays silent for STALL_TIMEOUT_S.
        self._last_activity: float = 0.0
        # Highest unpriced-row count already logged as a warning event.
        self._unpriced_seen: int = 0
        # Every DONE.md the model wrote: {"turn", "cost_usd"} (see `_stop_reason`).
        self._done_declared: list[dict[str, float]] = []

    def run(self) -> RunResult:
        """Runs turns until done, nudge cap, budget or leak, then writes result.json.

        Returns:
            the contender's final result
        """
        # Seeding happens before the clock starts: npm install and copying the
        # base game aren't the model's time.
        seed.seed_workspace(self.workspace, self.cfg.pack)
        snapshot.init_workspace(self.workspace)
        self.logs.mkdir(parents=True, exist_ok=True)
        # Turn 0 is the untouched base game: the "before" frame for the video
        # and the diff base for scoring.
        self._record_turn(0, "seed")
        self._start = time.monotonic()

        prompt = build_first_prompt(self.cfg.spec_path)
        nudge = (PROMPTS_DIR / "nudge.md").read_text()
        turn = nudges = api_retries = 0
        first_playable: tuple[int, float] | None = None

        while True:
            turn += 1
            end = self._run_turn(prompt, turn)
            # Servers the model started in the background (vite preview, dev
            # servers) outlive the claude process; stop them before building.
            _kill_strays(self.workspace)

            # Evidence after every turn, including the one the watchdog killed,
            # so the final state of the build is always captured.
            playable = self._record_turn(turn, end)
            if first_playable is None and playable:
                first_playable = (turn, time.monotonic() - self._start)

            if end == "api_error" and api_retries < MAX_API_RETRIES:
                # Infrastructure, not the model: resume without using a nudge.
                api_retries += 1
                self._append_jsonl("events.jsonl", {"event": "api_retry", "turn": turn})
                prompt = nudge
                continue

            reason = self._stop_reason(end, nudges, turn)
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
            done_declared=self._done_declared,
            api_retries=api_retries,
            pack=self.cfg.pack,
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

    def _stop_reason(self, end: TurnEnd, nudges: int, turn: int) -> StopReason | None:
        """Applies the stop rules after a turn, in priority order.

        Hard limits first (budget, leak, error), then the nudge cap. Writing
        DONE.md is not a stop while nudges remain: the file is moved to
        `logs/done-turn-NNN.md` and the model is nudged to keep building (the
        user's rule, so neither model leaves budget unspent by stopping early).
        A "stalled" turn is nudged too.

        Args:
            end: how the turn that just finished ended
            nudges: nudges sent so far
            turn: the turn that just finished

        Returns:
            why the run should stop, or None to send another nudge
        """
        if end in ("budget", "leak", "error"):
            return end
        if end == "api_error":  # retries used up (the turn loop retries before this)
            return "error"
        done = self.workspace / DONE_FILE
        if done.exists():
            self._done_declared.append({"turn": turn, "cost_usd": round(self._cost(), 4)})
            if nudges >= MAX_NUDGES or not self.cfg.nudge_on_done:
                return "declared_done"
            done.replace(self.logs / f"done-turn-{turn:03d}.md")
            return None
        if nudges >= MAX_NUDGES:
            return "nudge_cap"
        return None

    def _run_turn(self, prompt: str, turn: int) -> TurnEnd:
        """Runs one `claude -p` process under the budget/leak/stall watchdog.

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
            self._last_activity = time.monotonic()
            pump.start()
            while True:
                try:
                    proc.wait(timeout=METER_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                verdict = self._check_meter()
                if verdict is None and time.monotonic() - self._last_activity > STALL_TIMEOUT_S:
                    verdict = "stalled"
                    self._append_jsonl("events.jsonl", {"event": "stalled", "turn": turn})
                if verdict is not None:
                    _kill_tree(proc)
                    break
            # Let the pump flush the tail of the output before the log closes.
            pump.join(timeout=10)

        # If claude exited on its own, take one more reading: the last requests of
        # the turn land after the final mid-turn poll. A stalled turn still gets
        # a final reading, but budget/leak found there take priority.
        if verdict in (None, "stalled"):
            verdict = self._check_meter() or verdict
        if verdict is not None:
            return verdict
        if proc.returncode == 0:
            return "completed"
        return "api_error" if self._ended_on_api_error(log_path) else "error"

    @staticmethod
    def _ended_on_api_error(log_path: Path) -> bool:
        """True if the turn's final result event is a provider API error.

        Claude Code exits non-zero with a result like "API Error: The response
        stopped arriving" when the provider fails mid-turn; anything else that
        exits non-zero (a crash, a bad flag) stays a hard error.
        """
        for line in reversed(log_path.read_text().splitlines()):
            event = json.loads(line).get("event", {})
            if event.get("type") == "result":
                return bool(event.get("is_error")) and str(event.get("result", "")).startswith(
                    API_ERROR_PREFIX
                )
        return False

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
            self._last_activity = time.monotonic()
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
        # New spend means the model is working even if it printed nothing.
        if self._last is None or reading.cost_usd > self._last.cost_usd:
            self._last_activity = time.monotonic()
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


def _kill_strays(workspace: Path) -> None:
    """Stops every process whose working directory is inside the workspace.

    Models start servers in the background (`vite preview`, `npm run dev`)
    that escape the turn's process group and keep running after the turn, and
    after the race. Finding them by working directory catches them no matter
    how they were launched.

    Args:
        workspace: the contender's workspace
    """
    # `lsof -d cwd -Fpn` prints, per process, "p<pid>" then "n<cwd path>".
    out = subprocess.run(
        ["lsof", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=30
    ).stdout
    root = str(workspace.resolve())
    pid = None
    strays: list[int] = []
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None and pid != os.getpid():
            if line[1:] == root or line[1:].startswith(root + os.sep):
                strays.append(pid)
    for stray in strays:
        with contextlib.suppress(ProcessLookupError):
            os.kill(stray, signal.SIGKILL)
