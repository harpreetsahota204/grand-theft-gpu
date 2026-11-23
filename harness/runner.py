"""One contender's race: the turn loop, budget watchdog and per-turn evidence.

`harness.race` creates a `ContenderRun` per model and runs them in parallel
threads. Each turn is one headless `claude -p` process, run inside the
contender's sandbox (`harness.sandbox`) with a scrubbed environment. The first
turn gets the spec plus run rules; later turns get the fixed nudge, resuming
the same session. A watchdog polls Nexus (`harness.meter`) during the turn and
kills the process group if spend hits the budget, a foreign model shows up in
the usage rows, the meter goes blind for METER_BLIND_LIMIT_S, the race is
aborted, or the turn stalls (no output and no new spend for STALL_TIMEOUT_S).
After each turn, anything the model left running is stopped.

The harness fails closed: a crash inside a turn still kills that turn's
process tree, and `run()` always writes result.json, with `stop_reason`
"error" if the harness itself failed.

Declaring done doesn't end the run while nudges remain: DONE.md is moved to
`logs/done-turn-NNN.md` (the turn's commit still has it) and the model gets
the fixed nudge, so both models are pushed toward the full budget the same way.

Output layout under `<race_dir>/<contender>/`:
    workspace/            the seeded Vite project the model builds in
    history.git/          per-turn evidence commits of workspace/ (outside the model's reach)
    toolkit/              the modules tools/screenshot runs (read-only to the model)
    sandbox.sb            the contender's sandbox profile
    logs/turn-NNN.jsonl   timestamped Claude Code stream-json transcript per turn
    logs/cost.csv         timestamped Nexus spend readings
    logs/turns.jsonl      one row per turn (turn 0 = seeded base): build, load, errors
    logs/events.jsonl     harness events: leak, stall, meter, abort, errors (absent if none)
    logs/claude.pgid      process group of the running turn (for `buildoff stop`)
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
import traceback
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO, Literal, TextIO

from harness import meter, sandbox, seed, session, snapshot
from harness.config import (
    BUILD_DIR,
    DONE_FILE,
    MAX_API_RETRIES,
    MAX_NUDGES,
    METER_BLIND_LIMIT_S,
    METER_POLL_SECONDS,
    PROMPTS_DIR,
    STALL_TIMEOUT_S,
    TOOLS,
    Contender,
    RaceConfig,
)

StopReason = Literal[
    "declared_done", "nudge_cap", "budget", "leak", "meter_down", "aborted", "error"
]
TurnEnd = Literal[
    "completed", "stalled", "budget", "leak", "meter_down", "aborted", "error", "api_error"
]
# Turn endings that stop the run outright, whatever the nudge count.
HARD_STOPS: frozenset[str] = frozenset({"budget", "leak", "meter_down", "aborted", "error"})

# Claude Code's final message when the provider API fails mid-turn, e.g.
# "API Error: The response stopped arriving."
API_ERROR_PREFIX: str = "API Error"
# What Claude Code sends the model after a stream breaks off mid-response. A
# turn that ends after this with no tool call has lost its work to the
# connection, not to the model, so it's retried like an API error. In the
# 2026-11-21 dry runs, three of Kimi's turns ended this way with zero tool calls.
CUT_OFF_MARKER: str = "was cut off mid-stream"

# An empty MCP config plus --strict-mcp-config removes the user's connectors
# (Notion, Gmail, ...) from the race sessions.
EMPTY_MCP: str = '{"mcpServers":{}}'

# How often the watchdog wakes to check for an abort. The meter is polled less
# often (METER_POLL_SECONDS); this only bounds how fast Ctrl-C takes effect.
WATCH_TICK_S: float = 1.0

# Set by `harness.race` on SIGINT/SIGTERM. Every running turn is killed within
# WATCH_TICK_S and every contender stops with stop_reason "aborted".
ABORT: threading.Event = threading.Event()


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
        wall_seconds: total elapsed time, including the harness's per-turn
            build and screenshot
        model_seconds: time the model's turns actually ran (the race clock)
        first_playable_turn: first turn whose build loaded and rendered with no
            uncaught exception, if any
        first_playable_seconds: model_seconds at the end of that turn
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
    model_seconds: float
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
    parallel threads: they share no state (other than the ABORT flag) and use
    separate folders, sandboxes and sessions.

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
        self.history: Path = self.root / "history.git"
        self.toolkit: Path = self.root / "toolkit"
        self.profile: Path = self.root / "sandbox.sb"
        self.logs: Path = self.root / "logs"
        self.shots: Path = self.root / "shots"
        self.session_id: str = str(uuid.uuid4())
        self._last: meter.Reading | None = None
        self._start: float = 0.0
        # Sum of turn durations: the race clock, without the harness's own
        # build and screenshot time between turns.
        self._model_s: float = 0.0
        # Last time the turn showed life (new output line or new spend); the
        # watchdog kills a turn that stays silent for STALL_TIMEOUT_S.
        self._last_activity: float = 0.0
        # Last time Nexus returned a reading; the watchdog stops a turn whose
        # meter stays blind for METER_BLIND_LIMIT_S.
        self._last_reading_at: float = 0.0
        # Highest unpriced-row count already logged as a warning event.
        self._unpriced_seen: int = 0
        # Every DONE.md the model wrote: {"turn", "cost_usd"} (see `_stop_reason`).
        self._done_declared: list[dict[str, float]] = []
        # Written by `session.write` after seeding; passed on every turn.
        self._settings: Path = self.toolkit / session.SETTINGS_FILE
        self._agents: Path = self.toolkit / session.AGENTS_FILE

    def run(self) -> RunResult:
        """Runs turns until a stop rule fires, then writes result.json.

        result.json is written even if the harness itself fails partway, with
        stop_reason "error" and the traceback in events.jsonl.

        Returns:
            the contender's final result
        """
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        turn = nudges = api_retries = 0
        first_playable: tuple[int, float] | None = None
        reason: StopReason = "error"
        try:
            # Seeding happens before the clock starts: npm install and copying the
            # base game aren't the model's time.
            seed.seed_workspace(self.workspace, self.toolkit, self.cfg.pack)
            snapshot.init_history(self.history, self.workspace)
            sandbox.write_profile(self.profile, self.workspace, self.toolkit)
            session.write(self.toolkit, self.contender.model)
            # Turn 0 is the untouched base game: the "before" frame for the video
            # and the diff base for scoring.
            self._record_turn(0, "seed")
            self._start = time.monotonic()

            prompt = build_first_prompt(self.cfg.spec_path)
            nudge = (PROMPTS_DIR / "nudge.md").read_text()

            while True:
                if ABORT.is_set():
                    reason = "aborted"
                    break
                turn += 1
                end = self._run_turn(prompt, turn)

                # Evidence after every turn, including the one the watchdog killed,
                # so the final state of the build is always captured.
                if self._record_turn(turn, end) and first_playable is None:
                    first_playable = (turn, self._model_s)

                if end == "api_error" and api_retries < MAX_API_RETRIES:
                    # Infrastructure, not the model: resume without using a nudge.
                    api_retries += 1
                    self._event({"event": "api_retry", "turn": turn})
                    prompt = nudge
                    continue

                stop = self._stop_reason(end, nudges, turn)
                if stop is not None:
                    reason = stop
                    break

                nudges += 1
                prompt = nudge
        except Exception:
            self._event({"event": "harness_error", "turn": turn, "trace": traceback.format_exc()})
            reason = "error"
        finally:
            # Whatever happened above, nothing the model started outlives the run.
            _kill_strays(self.workspace)

        result = RunResult(
            contender=self.contender.name,
            session_id=self.session_id,
            stop_reason=reason,
            turns=turn,
            nudges=nudges,
            cost_usd=self._cost(),
            wall_seconds=round(time.monotonic() - self._start, 1) if self._start else 0.0,
            model_seconds=round(self._model_s, 1),
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
            whether this turn's game is playable: it built, loaded and rendered
            with no uncaught exception (see `snapshot.ShotResult.playable`)
        """
        message = f"turn {turn}" if turn else "seed: base game + assets"
        sha = snapshot.commit(self.history, self.workspace, message)
        built = snapshot.build(self.workspace)
        shot = (
            snapshot.screenshot(self.workspace / BUILD_DIR, self.shots / f"turn-{turn:03d}.png")
            if built.ok
            else snapshot.ShotResult(has_entry=False, loaded=False)
        )
        self._append_jsonl(
            "turns.jsonl",
            {
                "turn": turn,
                "end": end,
                "commit": sha,
                # Model time: the race clock, without the harness's own build and
                # screenshot work between turns. Turn 0 is before the clock starts.
                "elapsed_s": round(self._model_s, 1),
                "wall_s": round(time.monotonic() - self._start, 1) if turn else 0.0,
                "cost_usd": self._cost(),
                "build_ok": built.ok,
                "build_log_tail": built.log_tail,
                "has_entry": shot.has_entry,
                "loaded": shot.loaded,
                # A failed build gets a blank ShotResult, which is never playable.
                "playable": shot.playable,
                "page_errors": shot.page_errors[:20],
                "console_errors": shot.console_errors[:20],
            },
        )
        return shot.playable

    def _stop_reason(self, end: TurnEnd, nudges: int, turn: int) -> StopReason | None:
        """Applies the stop rules after a turn, in priority order.

        Hard limits first (budget, leak, dead meter, abort, error), then the
        nudge cap. Writing DONE.md is not a stop while nudges remain: the file is
        moved to `logs/done-turn-NNN.md` and the model is nudged to keep
        building (the user's rule, so neither model leaves budget unspent by
        stopping early). A "stalled" turn is nudged too: in practice a stall is
        the model blocking itself on a server that never exits.

        Args:
            end: how the turn that just finished ended
            nudges: nudges sent so far
            turn: the turn that just finished

        Returns:
            why the run should stop, or None to send another nudge
        """
        if end in HARD_STOPS:
            return end  # type: ignore[return-value]  # every hard stop is a StopReason
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
        """Runs one sandboxed `claude -p` process under the watchdog.

        Args:
            prompt: spec (turn 1) or the fixed nudge (later turns)
            turn: 1-based turn number, used for the log filename

        Returns:
            how the turn ended
        """
        log_path = self.logs / f"turn-{turn:03d}.jsonl"
        pgid_file = self.logs / "claude.pgid"
        env = sandbox.clean_env({"CLAUDE_CODE_SUBAGENT_MODEL": self.contender.model})
        cmd = sandbox.wrap(self._claude_cmd(prompt, first=turn == 1), self.profile)

        verdict: TurnEnd | None = None
        started = time.monotonic()
        with log_path.open("w") as log:
            # start_new_session puts claude and every shell it spawns in one
            # process group, so a kill takes down the whole tree.
            proc = subprocess.Popen(
                cmd,
                cwd=self.workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            # A reader thread drains the pipe while this thread runs the watchdog;
            # without it a full pipe buffer would stall claude.
            pump = threading.Thread(target=self._pump, args=(proc.stdout, log), daemon=True)
            try:
                # Recorded so `buildoff stop` can kill the turn even if this process dies.
                pgid_file.write_text(str(proc.pid))
                self._last_activity = self._last_reading_at = time.monotonic()
                pump.start()
                verdict = self._watch(proc, turn)
            finally:
                # Runs on a normal exit, a watchdog verdict, and a harness crash
                # alike. Background jobs share claude's process group, and
                # servers that escaped it are found by working directory.
                _kill_tree(proc)
                _kill_strays(self.workspace)
                pgid_file.unlink(missing_ok=True)
                self._model_s += time.monotonic() - started
            # Let the pump flush the tail of the output before the log closes.
            if pump.ident is not None:
                pump.join(timeout=10)

        # If claude exited on its own, take one more reading: the last requests of
        # the turn land after the final mid-turn poll. A stalled turn still gets
        # a final reading, but budget/leak found there take priority.
        if verdict in (None, "stalled"):
            verdict = self._check_meter() or verdict
        if verdict is not None:
            return verdict
        if proc.returncode == 0:
            return "api_error" if _ended_after_cut_off(log_path) else "completed"
        return "api_error" if _ended_on_api_error(log_path) else "error"

    def _watch(self, proc: subprocess.Popen[bytes], turn: int) -> TurnEnd | None:
        """Waits for claude to exit, enforcing abort, meter and stall limits.

        Args:
            proc: the running claude process
            turn: turn number, for event rows

        Returns:
            the verdict that ended the turn early, or None if claude exited itself
        """
        next_poll = time.monotonic() + METER_POLL_SECONDS
        while True:
            try:
                proc.wait(timeout=WATCH_TICK_S)
                return None
            except subprocess.TimeoutExpired:
                pass
            if ABORT.is_set():
                self._event({"event": "aborted", "turn": turn})
                return "aborted"
            if time.monotonic() < next_poll:
                continue
            next_poll = time.monotonic() + METER_POLL_SECONDS
            verdict = self._check_meter()
            if verdict is None and time.monotonic() - self._last_activity > STALL_TIMEOUT_S:
                verdict = "stalled"
                self._event({"event": "stalled", "turn": turn})
            if verdict is not None:
                return verdict

    def _pump(self, stream: IO[bytes], log: TextIO) -> None:
        """Copies claude's output into the turn log, stamping each line with race time.

        Each log row is `{"t": seconds_since_race_start, "event": <stream-json obj>}`,
        or `{"t": ..., "raw": text}` for non-JSON lines (stderr). The timestamps
        let the video be rendered from logs later, in sync across contenders.

        Args:
            stream: claude's combined stdout/stderr pipe
            log: open turn log file
        """
        try:
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
        except ValueError:
            # The log was closed under us: a process outside the turn's group kept
            # the pipe open past the turn. Its later output isn't part of the turn.
            return

    def _claude_cmd(self, prompt: str, first: bool) -> list[str]:
        """Builds the Claude Code command line for one turn.

        Both contenders get identical flags; only `--model` differs.

        Args:
            prompt: text for this turn
            first: True to start the session, False to resume it

        Returns:
            argv for subprocess (before the sandbox wrapper)
        """
        session = ["--session-id", self.session_id] if first else ["--resume", self.session_id]
        return [
            "claude",
            "-p",
            prompt,
            "--model",
            self.contender.model,
            *session,
            # Unattended run: tools are pre-approved instead of prompting. The
            # sandbox, not the permission mode, is what confines Bash.
            "--permission-mode",
            "acceptEdits",
            "--tools",
            ",".join(TOOLS),
            "--allowed-tools",
            ",".join(TOOLS),
            # Model pins, effort, compaction, the Stop hook and the playtester
            # subagent (harness.session); identical on both sides but the model ID.
            "--settings",
            str(self._settings),
            "--agents",
            str(self._agents),
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
            spend reached the cap, "meter_down" if Nexus has given no reading
            for METER_BLIND_LIMIT_S, otherwise None
        """
        reading = meter.read_session(self.session_id)
        now = time.monotonic()
        if reading is None:
            if now - self._last_reading_at > METER_BLIND_LIMIT_S:
                self._event({"event": "meter_down", "blind_s": round(now - self._last_reading_at)})
                return "meter_down"
            return None
        self._last_reading_at = now
        # New spend means the model is working even if it printed nothing.
        if self._last is None or reading.cost_usd > self._last.cost_usd:
            self._last_activity = now
        self._last = reading
        with (self.logs / "cost.csv").open("a") as f:
            f.write(f"{now - self._start:.1f},{reading.cost_usd:.6f}\n")

        # Unpriced rows mean spend is undercounted. Warn but keep racing; only log
        # when the count grows so a stuck row doesn't add a line every poll.
        if reading.unpriced > self._unpriced_seen:
            self._unpriced_seen = reading.unpriced
            self._event(
                {"event": "unpriced", "rows": reading.unpriced, "cost_usd": reading.cost_usd}
            )

        foreign = reading.models - {self.contender.nexus_model}
        if foreign:
            self._event({"event": "leak", "models": sorted(foreign)})
            return "leak"
        if reading.cost_usd >= self.cfg.budget_usd:
            return "budget"
        return None

    def _cost(self) -> float:
        """Returns the latest Nexus spend in USD, or 0.0 before the first reading."""
        return round(self._last.cost_usd, 6) if self._last else 0.0

    def _event(self, row: dict[str, object]) -> None:
        """Appends one harness event to events.jsonl."""
        self._append_jsonl("events.jsonl", row)

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


def _ended_on_api_error(log_path: Path) -> bool:
    """True if the turn's final result event is a provider API error.

    Claude Code exits non-zero with a result like "API Error: The response
    stopped arriving" when the provider fails mid-turn; anything else that
    exits non-zero (a crash, a bad flag) stays a hard error.
    """
    for line in reversed(log_path.read_text().splitlines()):
        try:
            event = json.loads(line).get("event") or {}
        except json.JSONDecodeError:
            continue  # a line cut off by the kill
        if isinstance(event, dict) and event.get("type") == "result":
            return bool(event.get("is_error")) and str(event.get("result", "")).startswith(
                API_ERROR_PREFIX
            )
    return False


def _ended_after_cut_off(log_path: Path) -> bool:
    """True if the model's stream was cut off and it made no tool call afterwards.

    See CUT_OFF_MARKER. A turn that recovered (made tool calls after the
    cut-off) counts as a normal turn.
    """
    cut_off = False
    for line in log_path.read_text().splitlines():
        try:
            event = json.loads(line).get("event") or {}
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        content = (event.get("message") or {}).get("content")
        if event.get("type") == "user" and CUT_OFF_MARKER in json.dumps(content):
            cut_off = True
        elif event.get("type") == "assistant" and isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content):
                cut_off = False
    return cut_off


def kill_group(pgid: int, grace_s: float = 10.0) -> None:
    """SIGTERMs a process group, then SIGKILLs it if anything is left after grace_s.

    Args:
        pgid: process group id (a `start_new_session` child's PID)
        grace_s: how long to wait for a clean exit
    """
    # The whole group can already be gone; that's the outcome we wanted.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)  # raises once no process is left in the group
        except (ProcessLookupError, PermissionError):
            return
        time.sleep(0.2)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stops a claude process and everything left in its process group.

    Called after every turn, not just on a kill: background jobs a model
    started (`npm run dev &`) stay in claude's group after claude exits.

    Args:
        proc: a process started with start_new_session=True
    """
    # start_new_session makes claude a group leader, so its PID is the group ID.
    # Using it directly (not os.getpgid) still works if claude itself already
    # exited but its children didn't.
    kill_group(proc.pid)
    # Reap claude so it doesn't linger as a zombie.
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)


def parse_lsof_cwds(out: str) -> list[tuple[int, str]]:
    """Parses `lsof -d cwd -Fpn` output into (pid, working directory) pairs.

    lsof prints, per process, a "p<pid>" line and then an "n<cwd path>" line.
    """
    pairs: list[tuple[int, str]] = []
    pid: int | None = None
    for line in out.splitlines():
        if line.startswith("p"):
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            pairs.append((pid, line[1:]))
    return pairs


def strays_in(pairs: list[tuple[int, str]], workspace: Path, own_pid: int) -> list[int]:
    """The PIDs (other than own_pid) whose working directory is inside workspace."""
    root = str(workspace.resolve())
    return [
        pid
        for pid, cwd in pairs
        if pid != own_pid and (cwd == root or cwd.startswith(root + os.sep))
    ]


def _kill_strays(workspace: Path) -> None:
    """Stops every process whose working directory is inside the workspace.

    Models start servers in the background (`vite preview`, `npm run dev`)
    that escape the turn's process group and keep running after the turn, and
    after the race. Finding them by working directory catches them no matter
    how they were launched.

    Args:
        workspace: the contender's workspace
    """
    try:
        out = subprocess.run(
            ["lsof", "-d", "cwd", "-Fpn"], capture_output=True, text=True, timeout=30
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    for stray in strays_in(parse_lsof_cwds(out), workspace, os.getpid()):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(stray, signal.SIGKILL)
