"""One contender's race: build turns, critic reviews, and the watchdog.

`harness.race` creates a `ContenderRun` per model and runs them in parallel
threads. A run is a loop of rounds:

1. **Build turn.** One headless `claude -p` process resuming the contender's
   builder session, inside its sandbox (`harness.sandbox`). Turn 1 gets the
   spec plus run rules; later turns get the critic's notes.
2. **Evidence.** The harness commits the workspace to `history.git`, builds the
   game and screenshots it.
3. **Critic review.** A fresh `claude -p` session of the *same* model, with no
   memory of building, plays the game read-only (`prompts/critic.md`) and
   writes a JSON verdict to `tools/shots/verdict.json`: the tier reached, the
   route that showed it, and ranked notes for the builder. Each critic gets the
   last review's tier and route to replay first, so a tier it can't reach by
   scripted play isn't silently dropped. The tier never ends the run: a
   same-model critic is a coach, and builds are scored afterwards against
   `scoring/checklist.md`.
4. The notes go back to the builder in the `prompts/nudge.md` template, and
   the next round starts.

A run ends on the budget or on a safety stop (leak, dead meter, abort, harness
error). The smoke test (`RaceConfig.stop_on_done`) also stops at the first
DONE.md, after one review.

A watchdog polls Nexus (`harness.meter`) during every session, builder and
critic alike, and kills it if total spend (all of the contender's sessions)
hits the budget, a foreign model shows up, the meter goes blind for
METER_BLIND_LIMIT_S, the race is aborted, or the session stalls (no output and
no new spend for STALL_TIMEOUT_S). After each session, anything it left
running is stopped. A crash still kills the running session, and `run()`
always writes result.json.

Output layout under `<race_dir>/<contender>/`:
    workspace/             the seeded Vite project the model builds in
    history.git/           per-turn evidence commits of workspace/ (outside the model's reach)
    toolkit/               what runs inside the sandbox: screenshot modules, Stop hook, settings
    sandbox.sb, critic.sb  sandbox profiles for the builder and the read-only critic
    logs/turn-NNN.jsonl    builder transcript per turn ({"t": seconds, "event": ...})
    logs/critic-NNN.jsonl  critic transcript after turn NNN
    logs/reviews.jsonl     one row per review: tier, route, notes, its cost and time
    logs/cost.csv          timestamped total spend (all sessions) per Nexus
    logs/turns.jsonl       one row per turn (turn 0 = seeded base): build, load, errors
    logs/events.jsonl      harness events: leak, stall, meter, abort, retries, errors
    logs/claude.pgid       process group of the running session (for `buildoff stop`)
    shots/turn-NNN.png     screenshot of the built game after each turn (000 = base)
    shots/critic-NNN/      the screenshots the critic took reviewing turn NNN
    result.json            final outcome
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO, Literal, TextIO

from harness import meter, sandbox, seed, session, snapshot
from harness.config import (
    BUILD_DIR,
    CRITIC_TOOLS,
    DONE_FILE,
    MAX_API_RETRIES,
    METER_BLIND_LIMIT_S,
    METER_POLL_SECONDS,
    PROMPTS_DIR,
    STALL_TIMEOUT_S,
    TOOLS,
    Contender,
    RaceConfig,
)

StopReason = Literal["declared_done", "budget", "leak", "meter_down", "aborted", "error"]
TurnEnd = Literal[
    "completed", "stalled", "budget", "leak", "meter_down", "aborted", "error", "api_error"
]
# Session endings that stop the run outright.
HARD_STOPS: frozenset[str] = frozenset({"budget", "leak", "meter_down", "aborted", "error"})

# Claude Code's final message when the provider API fails mid-turn, e.g.
# "API Error: The response stopped arriving."
API_ERROR_PREFIX: str = "API Error"
# What Claude Code sends the model after a stream breaks off mid-response. A
# turn that ends after this with no tool call has lost its work to the
# connection, not to the model, so it's retried like an API error. In the
# 2026-11-21 dry runs, three of Kimi's turns ended this way with zero tool calls.
CUT_OFF_MARKER: str = "was cut off mid-stream"

# What the builder is told when the critic produced no usable verdict (its
# session failed, or it wrote no valid verdict.json).
NO_REVIEW_NOTES: str = "The critic could not finish a review this round."
# What the first critic is told in place of the last review's tier and route.
NO_LAST_REVIEW: str = "Nothing yet: this is the first review."

# An empty MCP config plus --strict-mcp-config removes the user's connectors
# (Notion, Gmail, ...) from the race sessions.
EMPTY_MCP: str = '{"mcpServers":{}}'

# How often the watchdog wakes to check for an abort. The meter is polled less
# often (METER_POLL_SECONDS); this only bounds how fast Ctrl-C takes effect.
WATCH_TICK_S: float = 1.0

# Set by `harness.race` on SIGINT/SIGTERM. Every running session is killed within
# WATCH_TICK_S and every contender stops with stop_reason "aborted".
ABORT: threading.Event = threading.Event()


@dataclass(frozen=True)
class Review:
    """A critic's verdict, read from the `verdict.json` it writes.

    Attributes:
        parsed: whether a valid verdict file was found
        tier: highest tier the critic saw fully working, if given
        route: the tools/screenshot steps, from a fresh load, that showed that tier
        notes: what the builder should do next, ranked, one "[group] note" per line
        problem: why the verdict was rejected (empty when parsed)
    """

    parsed: bool
    tier: int | None = None
    route: str = ""
    notes: str = ""
    problem: str = ""


@dataclass
class RunResult:
    """Final outcome of one contender's race, written to result.json.

    Attributes:
        contender: contender name
        session_id: the builder's Claude Code session UUID (`nexus claude usage --session`)
        critic_sessions: every critic session UUID, in order
        stop_reason: why the run ended
        turns: builder turns run
        reviews: critic reviews run
        last_tier: the tier the last critic review reported, if any
        cost_usd: final total spend per Nexus, builder and critics together
        wall_seconds: total elapsed time, including the harness's own work
        model_seconds: time the model's sessions ran, builder and critic (the race clock)
        first_playable_turn: first turn whose build loaded and rendered with no
            uncaught exception, if any
        first_playable_seconds: model_seconds at the end of that turn
        models_seen: every model Nexus logged across the contender's sessions
        api_retries: turns resumed after a provider API error or cut-off stream
        pack: which asset pack the workspace was seeded with
    """

    contender: str
    session_id: str
    critic_sessions: list[str]
    stop_reason: StopReason
    turns: int
    reviews: int
    last_tier: int | None
    cost_usd: float
    wall_seconds: float
    model_seconds: float
    first_playable_turn: int | None
    first_playable_seconds: float | None
    models_seen: list[str]
    api_retries: int
    pack: str


@dataclass
class _Spend:
    """Latest Nexus reading per session, for one contender.

    The budget and the leak check cover all of a contender's sessions: one
    builder session (resumed every turn) plus one fresh critic session per review.

    Attributes:
        cost: latest cost per session ID, USD
        models: models seen per session ID
        unpriced: unpriced row count per session ID
    """

    cost: dict[str, float] = field(default_factory=dict)
    models: dict[str, frozenset[str]] = field(default_factory=dict)
    unpriced: dict[str, int] = field(default_factory=dict)

    def total(self) -> float:
        """Total spend across sessions, USD."""
        return sum(self.cost.values())

    def all_models(self) -> frozenset[str]:
        """Every model seen in any session."""
        return frozenset().union(*self.models.values())


class ContenderRun:
    """Drives one model through the race: build, review, check, repeat.

    Created by `harness.race` with the shared `RaceConfig`; `run()` blocks until
    the contender stops and returns its `RunResult`. Safe to run two instances in
    parallel threads: they share no state (other than the ABORT flag) and use
    separate folders, sandboxes and sessions.

    Attributes:
        contender: which model this run drives
        cfg: race-wide settings
        root: this contender's output folder
        session_id: the builder's fixed UUID, so Nexus can be queried mid-turn
    """

    def __init__(self, contender: Contender, cfg: RaceConfig) -> None:
        """Sets up paths and a fresh builder session ID; touches nothing on disk yet."""
        self.contender = contender
        self.cfg = cfg
        self.root: Path = cfg.race_dir / contender.name
        self.workspace: Path = self.root / "workspace"
        self.history: Path = self.root / "history.git"
        self.toolkit: Path = self.root / "toolkit"
        self.profile: Path = self.root / "sandbox.sb"
        self.critic_profile: Path = self.root / "critic.sb"
        self.logs: Path = self.root / "logs"
        self.shots: Path = self.root / "shots"
        self.session_id: str = str(uuid.uuid4())
        self.critic_sessions: list[str] = []
        self._spend = _Spend()
        self._start: float = 0.0
        # Sum of session durations: the race clock, without the harness's own
        # build, screenshot and check work between sessions.
        self._model_s: float = 0.0
        # Last time the running session showed life (new output or new spend);
        # the watchdog kills a session that stays silent for STALL_TIMEOUT_S.
        self._last_activity: float = 0.0
        # Last time Nexus returned a reading; the watchdog stops a session whose
        # meter stays blind for METER_BLIND_LIMIT_S.
        self._last_reading_at: float = 0.0
        # Highest unpriced-row total already logged as a warning event.
        self._unpriced_seen: int = 0
        # Wall-clock start of the latest review; only screenshots newer than this are its own.
        self._review_started: float = 0.0

    def run(self) -> RunResult:
        """Runs rounds until a stop rule fires, then writes result.json.

        result.json is written even if the harness itself fails partway, with
        stop_reason "error" and the traceback in events.jsonl.

        Returns:
            the contender's final result
        """
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        turn = reviews = api_retries = 0
        # The latest parsed review, whose route the next critic replays first.
        last_review: Review | None = None
        first_playable: tuple[int, float] | None = None
        reason: StopReason = "error"
        try:
            # Seeding happens before the clock starts: npm install and copying the
            # base game aren't the model's time.
            seed.seed_workspace(self.workspace, self.toolkit, self.cfg.pack)
            snapshot.init_history(self.history)
            sandbox.write_profile(self.profile, self.workspace, self.toolkit)
            sandbox.write_profile(self.critic_profile, self.workspace, self.toolkit, read_only=True)
            session.write(self.toolkit, self.contender.model)
            # Turn 0 is the untouched base game: the "before" frame for the video
            # and the diff base for scoring.
            self._record_turn(0, "seed")
            self._start = time.monotonic()

            prompt = build_first_prompt(self.cfg.spec_path, self.cfg.budget_usd)
            notes = ""
            while True:
                if ABORT.is_set():
                    reason = "aborted"
                    break
                turn += 1
                end = self._run_turn(prompt, turn)

                # Evidence after every turn, including one the watchdog killed,
                # so the final state of the build is always captured.
                if self._record_turn(turn, end) and first_playable is None:
                    first_playable = (turn, self._model_s)

                if end == "api_error" and api_retries < MAX_API_RETRIES:
                    # Infrastructure, not the model: resume with the same notes.
                    api_retries += 1
                    self._event({"event": "api_retry", "turn": turn})
                    prompt = nudge_text(notes, self._cost(), self.cfg.budget_usd)
                    continue
                if end in HARD_STOPS:
                    reason = end  # type: ignore[assignment]  # every hard stop is a StopReason
                    break
                if end == "api_error":  # retries used up
                    reason = "error"
                    break

                review = self._review(turn, last_review)
                if isinstance(review, str):  # a hard stop during the critic's session
                    reason = review  # type: ignore[assignment]
                    break
                reviews += 1
                if review.parsed:
                    last_review = review

                if self.cfg.stop_on_done and (self.workspace / DONE_FILE).exists():
                    reason = "declared_done"
                    break
                notes = review.notes if review.parsed else NO_REVIEW_NOTES
                prompt = nudge_text(notes, self._cost(), self.cfg.budget_usd)
        except Exception:
            self._event({"event": "harness_error", "turn": turn, "trace": traceback.format_exc()})
            reason = "error"
        finally:
            # Whatever happened above, nothing the model started outlives the run.
            _kill_strays(self.workspace)

        result = RunResult(
            contender=self.contender.name,
            session_id=self.session_id,
            critic_sessions=self.critic_sessions,
            stop_reason=reason,
            turns=turn,
            reviews=reviews,
            last_tier=last_review.tier if last_review else None,
            cost_usd=self._cost(),
            wall_seconds=round(time.monotonic() - self._start, 1) if self._start else 0.0,
            model_seconds=round(self._model_s, 1),
            first_playable_turn=first_playable[0] if first_playable else None,
            first_playable_seconds=round(first_playable[1], 1) if first_playable else None,
            models_seen=sorted(self._spend.all_models()),
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
                # screenshot work between sessions. Turn 0 is before the clock starts.
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

    def _run_turn(self, prompt: str, turn: int) -> TurnEnd:
        """Runs one builder turn: the builder session, resumed after turn 1.

        Args:
            prompt: spec (turn 1) or the critic's notes (later turns)
            turn: 1-based turn number, used for the log filename

        Returns:
            how the turn ended
        """
        resume = ["--session-id", self.session_id] if turn == 1 else ["--resume", self.session_id]
        cmd = self._claude_cmd(prompt, resume, TOOLS, session.SETTINGS_FILE, agents=True)
        log_path = self.logs / f"turn-{turn:03d}.jsonl"
        end = self._run_session(cmd, self.profile, self.session_id, log_path, f"turn {turn}")
        if end == "completed" and _ended_after_cut_off(log_path):
            return "api_error"
        return end

    def _review(self, turn: int, last: Review | None) -> Review | StopReason:
        """Runs the critic after a turn and parses its verdict.

        The critic is a fresh session of the same model (no memory of building),
        in the read-only sandbox, with only Bash and Read.

        Args:
            turn: the turn just finished
            last: the latest parsed review, whose tier and route this critic replays first

        Returns:
            the review (unparsed if the critic failed or wrote no valid verdict),
            or a stop reason if a hard stop fired during the critic's session
        """
        # A verdict left over from the last round must never count for this one.
        verdict_path = self.workspace / VERDICT_FILE
        verdict_path.unlink(missing_ok=True)
        critic_id = str(uuid.uuid4())
        self.critic_sessions.append(critic_id)
        prompt = critic_text(self.cfg.spec_path, self.cfg.budget_usd, last)
        cmd = self._claude_cmd(
            prompt, ["--session-id", critic_id], CRITIC_TOOLS, session.CRITIC_SETTINGS_FILE
        )
        log_path = self.logs / f"critic-{turn:03d}.jsonl"
        # Wall-clock start: only screenshots newer than this are this critic's.
        self._review_started = time.time()
        end = self._run_session(cmd, self.critic_profile, critic_id, log_path, f"review {turn}")
        kept = keep_critic_shots(
            self.workspace, self.shots / f"critic-{turn:03d}", self._review_started
        )
        if end in HARD_STOPS:
            return end  # type: ignore[return-value]  # every hard stop is a StopReason
        review = parse_review(verdict_path)
        self._append_jsonl(
            "reviews.jsonl",
            {
                "turn": turn,
                "end": end,
                "cost_usd": self._cost(),
                # This critic session alone (it has its own Nexus session ID).
                "review_cost_usd": round(self._spend.cost.get(critic_id, 0.0), 6),
                "review_seconds": round(time.time() - self._review_started, 1),
                "critic_shots": kept,
            }
            | asdict(review),
        )
        return review

    def _run_session(
        self, cmd: list[str], profile: Path, session_id: str, log_path: Path, label: str
    ) -> TurnEnd:
        """Runs one sandboxed `claude -p` process (builder or critic) under the watchdog.

        Args:
            cmd: the Claude Code argv (before the sandbox wrapper)
            profile: the sandbox profile to run it under
            session_id: the session Nexus meters for this process
            log_path: where to write its timestamped transcript
            label: e.g. "turn 3" or "review 3", for event rows

        Returns:
            how the session ended
        """
        pgid_file = self.logs / "claude.pgid"
        env = sandbox.clean_env({"CLAUDE_CODE_SUBAGENT_MODEL": self.contender.model})

        ending: TurnEnd | None = None
        started = time.monotonic()
        with log_path.open("w") as log:
            # start_new_session puts claude and every shell it spawns in one
            # process group, so a kill takes down the whole tree.
            proc = subprocess.Popen(
                sandbox.wrap(cmd, profile),
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
                # Recorded so `buildoff stop` can kill it even if this process dies.
                pgid_file.write_text(str(proc.pid))
                self._last_activity = self._last_reading_at = time.monotonic()
                pump.start()
                ending = self._watch(proc, session_id, label)
            finally:
                # Runs on a normal exit, a watchdog stop, and a harness crash
                # alike. Background jobs share claude's process group, and
                # servers that escaped it are found by working directory.
                _kill_tree(proc)
                _kill_strays(self.workspace)
                pgid_file.unlink(missing_ok=True)
                self._model_s += time.monotonic() - started
            # Let the pump flush the tail of the output before the log closes.
            if pump.ident is not None:
                pump.join(timeout=10)

        # If claude exited on its own, take one more reading: the last requests
        # land after the final mid-session poll. A stalled session still gets a
        # final reading, but budget/leak found there take priority.
        if ending in (None, "stalled"):
            ending = self._check_meter(session_id) or ending
        if ending is not None:
            return ending
        if proc.returncode == 0:
            return "completed"
        return "api_error" if _ended_on_api_error(log_path) else "error"

    def _watch(self, proc: subprocess.Popen[bytes], session_id: str, label: str) -> TurnEnd | None:
        """Waits for claude to exit, enforcing abort, meter and stall limits.

        Args:
            proc: the running claude process
            session_id: the session to meter
            label: e.g. "turn 3", for event rows

        Returns:
            how the watchdog ended the session early, or None if claude exited itself
        """
        next_poll = time.monotonic() + METER_POLL_SECONDS
        while True:
            try:
                proc.wait(timeout=WATCH_TICK_S)
                return None
            except subprocess.TimeoutExpired:
                pass
            if ABORT.is_set():
                self._event({"event": "aborted", "during": label})
                return "aborted"
            if time.monotonic() < next_poll:
                continue
            next_poll = time.monotonic() + METER_POLL_SECONDS
            ending = self._check_meter(session_id)
            if ending is None and time.monotonic() - self._last_activity > STALL_TIMEOUT_S:
                ending = "stalled"
                self._event({"event": "stalled", "during": label})
            if ending is not None:
                return ending

    def _pump(self, stream: IO[bytes], log: TextIO) -> None:
        """Copies claude's output into the session log, stamping each line with race time.

        Each log row is `{"t": seconds_since_race_start, "event": <stream-json obj>}`,
        or `{"t": ..., "raw": text}` for non-JSON lines (stderr). The timestamps
        let the video be rendered from logs later, in sync across contenders.

        Args:
            stream: claude's combined stdout/stderr pipe
            log: open session log file
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
            # The log was closed under us: a process outside the session's group
            # kept the pipe open past its end. Its later output isn't part of it.
            return

    def _claude_cmd(
        self,
        prompt: str,
        session_args: list[str],
        tools: tuple[str, ...],
        settings_file: str,
        agents: bool = False,
    ) -> list[str]:
        """Builds the Claude Code command line for a builder turn or a critic review.

        Both contenders get identical flags; only the model ID differs.

        Args:
            prompt: text for this session
            session_args: `--session-id <id>` to start one, `--resume <id>` to continue
            tools: the tools the session may use
            settings_file: settings file in the toolkit (builder or critic)
            agents: True to offer the playtester subagent (builder only)

        Returns:
            argv for subprocess (before the sandbox wrapper)
        """
        toolkit = self.toolkit.resolve()
        return [
            "claude",
            "-p",
            prompt,
            "--model",
            self.contender.model,
            *session_args,
            # Unattended run: tools are pre-approved instead of prompting. The
            # sandbox, not the permission mode, is what confines Bash.
            "--permission-mode",
            "acceptEdits",
            "--tools",
            ",".join(tools),
            "--allowed-tools",
            ",".join(tools),
            # Model pins, effort, compaction (and for the builder the Stop hook);
            # identical on both sides but the model ID (harness.session).
            "--settings",
            str(toolkit / settings_file),
            *(["--agents", str(toolkit / session.AGENTS_FILE)] if agents else []),
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

    def _check_meter(self, session_id: str) -> TurnEnd | None:
        """Polls Nexus for one session, logs the total, and says whether to stop.

        The budget and the leak check apply to the contender's total across all
        its sessions. Also writes an `unpriced` warning to events.jsonl when Nexus
        reports rows it couldn't price (spend undercounted); that never stops it.

        Args:
            session_id: the session currently running

        Returns:
            "leak" if a model other than the contender's appears, "budget" if
            total spend reached the cap, "meter_down" if Nexus has given no
            reading for METER_BLIND_LIMIT_S, otherwise None
        """
        reading = meter.read_session(session_id)
        now = time.monotonic()
        if reading is None:
            if now - self._last_reading_at > METER_BLIND_LIMIT_S:
                self._event({"event": "meter_down", "blind_s": round(now - self._last_reading_at)})
                return "meter_down"
            return None
        self._last_reading_at = now
        # New spend means the model is working even if it printed nothing.
        if reading.cost_usd > self._spend.cost.get(session_id, -1.0):
            self._last_activity = now
        self._spend.cost[session_id] = reading.cost_usd
        self._spend.models[session_id] = reading.models
        self._spend.unpriced[session_id] = reading.unpriced
        total = self._spend.total()
        with (self.logs / "cost.csv").open("a") as f:
            f.write(f"{now - self._start:.1f},{total:.6f}\n")

        # Unpriced rows mean spend is undercounted. Warn but keep racing; only log
        # when the count grows so a stuck row doesn't add a line every poll.
        unpriced = sum(self._spend.unpriced.values())
        if unpriced > self._unpriced_seen:
            self._unpriced_seen = unpriced
            self._event({"event": "unpriced", "rows": unpriced, "cost_usd": total})

        foreign = self._spend.all_models() - {self.contender.nexus_model}
        if foreign:
            self._event({"event": "leak", "models": sorted(foreign)})
            return "leak"
        if total >= self.cfg.budget_usd:
            return "budget"
        return None

    def _cost(self) -> float:
        """Returns the contender's total Nexus spend in USD (0.0 before any reading)."""
        return round(self._spend.total(), 6)

    def _event(self, row: dict[str, object]) -> None:
        """Appends one harness event to events.jsonl."""
        self._append_jsonl("events.jsonl", row)

    def _append_jsonl(self, name: str, row: dict[str, object]) -> None:
        """Appends one JSON row to a file in this contender's logs folder."""
        with (self.logs / name).open("a") as f:
            f.write(json.dumps(row) + "\n")


def usd(amount: float) -> str:
    """Formats dollars the way the prompts show them: "$25", "$12.40"."""
    return f"${amount:,.0f}" if amount == int(amount) else f"${amount:,.2f}"


def brief_text(spec_path: Path, budget_usd: float) -> str:
    """The game brief with the race's real budget filled in.

    The spec says `{budget}` instead of a fixed figure: v7 told every model
    "$100" even in $25 runs, so Opus scoped a $100 game and spent its whole
    budget in turn 1.
    """
    return spec_path.read_text().strip().replace("{budget}", usd(budget_usd))


def build_first_prompt(spec_path: Path, budget_usd: float) -> str:
    """Joins the game brief with the run rules both models must follow.

    The rules (entry file, the critic, DONE.md) are kept out of the spec so the
    spec reads as a pure game brief and the harness contract lives in one file.

    Args:
        spec_path: markdown game spec
        budget_usd: the per-contender budget

    Returns:
        the full first-turn prompt
    """
    rules = (PROMPTS_DIR / "run_rules.md").read_text()
    return f"{brief_text(spec_path, budget_usd)}\n\n{rules.strip()}\n"


def nudge_text(notes: str, spent_usd: float, budget_usd: float) -> str:
    """The builder's next prompt: the locked nudge template around the critic's notes.

    It also reports spend so far (builder and critics, per Nexus): without it a
    model can't pace itself against the budget.
    """
    template = (PROMPTS_DIR / "nudge.md").read_text()
    return (
        template.replace("{notes}", notes.strip() or NO_REVIEW_NOTES)
        .replace("{spent}", usd(spent_usd))
        .replace("{budget}", usd(budget_usd))
    )


def critic_text(spec_path: Path, budget_usd: float, last: Review | None = None) -> str:
    """The critic's prompt: the locked critic template around the game brief.

    It also carries the last review's tier and route. Each critic starts fresh,
    and in the v12 race Kimi's critics flipped between Tier 2 and Tier 4 when one
    couldn't script its way to a mission the one before had reached.

    Args:
        spec_path: markdown game spec
        budget_usd: the per-contender budget
        last: the latest parsed review, or None before the first one

    Returns:
        the critic's full prompt
    """
    if last is None:
        last_review = NO_LAST_REVIEW
    else:
        last_review = (
            f"It judged Tier {last.tier}. Its route:\n\n{last.route.strip() or '(none given)'}"
        )
    template = (PROMPTS_DIR / "critic.md").read_text()
    return template.replace("{last_review}", last_review).replace(
        "{brief}", brief_text(spec_path, budget_usd)
    )


# Where the critic writes its verdict, relative to the workspace. It sits in
# tools/shots/ because that's the one workspace folder the critic's sandbox lets
# it write besides build output.
VERDICT_FILE: str = "tools/shots/verdict.json"

# The note groups, in the order prompts/critic.md ranks them.
NOTE_GROUPS: tuple[str, ...] = ("blocker", "core loop", "next tier", "look and feel", "polish")


def parse_review(verdict_path: Path) -> Review:
    """Reads and schema-checks the verdict file the critic wrote.

    A file instead of the reply's last line, because critics wrapped, split or
    trailed that line often enough to need two fallback parsers.

    Args:
        verdict_path: the critic's `tools/shots/verdict.json`

    Returns:
        the review, or `Review(parsed=False, problem=...)` if the file is
        missing or doesn't match the schema
    """
    try:
        verdict = json.loads(verdict_path.read_text())
    except FileNotFoundError:
        return Review(parsed=False, problem="no verdict.json")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return Review(parsed=False, problem=f"verdict.json is not JSON: {exc}")
    problem = _verdict_problem(verdict)
    if problem:
        return Review(parsed=False, problem=problem)
    return Review(
        parsed=True,
        tier=verdict["tier"],
        route=verdict["route"],
        notes="\n".join(
            f"{i}. [{n['group']}] {n['note'].strip()}" for i, n in enumerate(verdict["notes"], 1)
        ),
    )


def _verdict_problem(verdict: object) -> str:
    """Checks a verdict against the schema in prompts/critic.md.

    Args:
        verdict: the decoded verdict.json

    Returns:
        what's wrong with it, or "" if it's valid
    """
    if not isinstance(verdict, dict):
        return "verdict is not an object"
    tier = verdict.get("tier")
    # bool is an int subclass; True must not pass as tier 1.
    if not isinstance(tier, int) or isinstance(tier, bool) or not 0 <= tier <= 4:
        return "tier must be an integer from 0 to 4"
    if not isinstance(verdict.get("route"), str):
        return "route must be a string"
    notes = verdict.get("notes")
    if not isinstance(notes, list) or not notes:
        return "notes must be a non-empty list"
    for n in notes:
        if not isinstance(n, dict) or n.get("group") not in NOTE_GROUPS:
            return f"each note needs a group from {', '.join(NOTE_GROUPS)}"
        if not isinstance(n.get("note"), str) or not n["note"].strip():
            return "each note needs non-empty text"
    return ""


def _events(log_path: Path) -> list[dict]:
    """The Claude Code events in a session log (runner format), in order.

    Skips stderr lines (no "event") and a last line cut off by a kill.
    """
    events = []
    for line in log_path.read_text().splitlines():
        try:
            event = json.loads(line).get("event")
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _ended_on_api_error(log_path: Path) -> bool:
    """True if the session's final result event is a provider API error.

    Claude Code exits non-zero with a result like "API Error: The response
    stopped arriving" when the provider fails mid-session; anything else that
    exits non-zero (a crash, a bad flag) stays a hard error.
    """
    last = next((e for e in reversed(_events(log_path)) if e.get("type") == "result"), None)
    return (
        last is not None
        and bool(last.get("is_error"))
        and str(last.get("result", "")).startswith(API_ERROR_PREFIX)
    )


def _ended_after_cut_off(log_path: Path) -> bool:
    """True if the model's stream was cut off and it made no tool call afterwards.

    See CUT_OFF_MARKER. A turn that recovered (made tool calls after the
    cut-off) counts as a normal turn.
    """
    cut_off = False
    for event in _events(log_path):
        # Not every event's "message" is an API message: a `permission_denied`
        # system event carries a plain string there.
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if event.get("type") == "user" and CUT_OFF_MARKER in json.dumps(content):
            cut_off = True
        elif (
            event.get("type") == "assistant"
            and isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        ):
            cut_off = False
    return cut_off


def keep_critic_shots(workspace: Path, dest: Path, since: float) -> list[str]:
    """Copies the screenshots a critic took this round out of the workspace.

    The critic saves shots in the workspace's `tools/shots/`, which the builder
    can overwrite or delete and `history.git` leaves out. Copying them into the
    contender's own `shots/critic-NNN/` keeps each round's evidence for the
    video and for tracing reviews.

    Args:
        workspace: the contender's game folder
        dest: where this round's shots go (created only if there are any)
        since: wall-clock time the critic started; older shots aren't its own

    Returns:
        the copied file names, oldest first
    """
    src = workspace / "tools" / "shots"
    fresh = sorted(
        (p for p in src.glob("*.png") if p.is_file() and p.stat().st_mtime >= since),
        key=lambda p: p.stat().st_mtime,
    )
    if fresh:
        dest.mkdir(parents=True, exist_ok=True)
    for p in fresh:
        shutil.copy2(p, dest / p.name)
    return [p.name for p in fresh]


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
