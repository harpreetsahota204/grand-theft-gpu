"""Durable vote, play-time and input-log storage for the blind arena.

Backs `arena.app` with an ACID SQLite store (WAL mode) plus append-only JSONL
mirrors that can optionally sync to a private Hugging Face Dataset via
`huggingface_hub.CommitScheduler`, surviving Space restarts at zero cost.

Main entry points:
- `VoteStore`: manages sessions, anti-spoof play-time heartbeats, ballots,
  per-IP rate limits, input event logs, and tallies
- `QUESTIONS`: the four locked pairwise rubric questions from `scoring/checklist.md`
- `RateLimitedError`: raised when one IP opens too many sessions or casts too many votes
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal, TypedDict

logger = logging.getLogger(__name__)

# Locked pairwise rubric questions matching scoring/checklist.md:105.
QUESTIONS: tuple[str, ...] = (
    "plays_better",
    "looks_better",
    "better_main_character",
    "overall",
)

VALID_PICKS: frozenset[str] = frozenset({"a", "b", "tie"})

# Upper bound on play seconds credited per heartbeat call (matches 15s client interval + grace).
MAX_HEARTBEAT_STEP_S: float = 20.0

# Slack added to wall-clock elapsed time when crediting a heartbeat (network jitter).
HEARTBEAT_GRACE_S: float = 1.5

# Hard cap on logged input events per session, so one stuck key-repeat loop can't fill the disk.
MAX_EVENTS_PER_SESSION: int = 200_000

# Rate-limit windows for the per-IP caps.
SESSION_WINDOW_S: float = 3600.0
VOTE_WINDOW_S: float = 86400.0

# Shared SQL for inserting one ballot row (used by both live voting and HF hydration).
_INSERT_VOTE_SQL: str = """
INSERT OR IGNORE INTO votes (
    sid, race_id, a_build, b_build, a_contender, b_contender,
    slot_picks_json, contender_picks_json, play_a_s, play_b_s, submitted_at, ip_hash
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class RateLimitedError(Exception):
    """Raised when one client IP exceeds the session or vote cap for its window."""


class QuestionTally(TypedDict):
    """Per-question aggregate counts keyed by contender name plus ties."""

    counts: dict[str, int]
    total: int


class VoteSummary(TypedDict):
    """Snapshot of a voter's submitted ballot (server-side de-blinded)."""

    sid: str
    a_build: str
    b_build: str
    a_contender: str
    b_contender: str
    slot_picks: dict[str, str]
    contender_picks: dict[str, str]
    play_a_s: float
    play_b_s: float
    submitted_at: float


@dataclass(frozen=True)
class SessionState:
    """Current server-tracked play time and vote status for one visitor session.

    Attributes:
        sid: signed session ID
        a_build: opaque build ID assigned to slot A
        b_build: opaque build ID assigned to slot B
        play_a_s: accumulated verified active seconds in slot A
        play_b_s: accumulated verified active seconds in slot B
        voted: True once this session has submitted a ballot
    """

    sid: str
    a_build: str
    b_build: str
    play_a_s: float
    play_b_s: float
    voted: bool


def _append_locked(path: Path, line: str) -> None:
    """Appends one line under an exclusive OS file lock so concurrent workers never interleave."""
    with path.open("a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line)
            fh.flush()
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class VoteStore:
    """Thread-safe SQLite store for blind play timers, pairwise votes and input logs.

    Created once on app startup (`arena.app`) and shared across HTTP handlers.
    Optionally mirrors every committed vote and event batch into JSONL files and
    hydrates votes from a Hugging Face Dataset on startup so Space restarts keep
    historical tallies.
    """

    def __init__(
        self,
        data_dir: Path,
        build_to_contender: dict[str, str],
        race_id: str = "",
        dataset_repo: str = "",
        hf_token: str | None = None,
    ) -> None:
        """Initializes SQLite tables, optional HF Dataset hydration, and background sync.

        Args:
            data_dir: writable directory for `votes.db` and the JSONL mirrors
            build_to_contender: mapping from opaque build ID -> contender key (e.g. "kimi")
            race_id: identifier of the race being judged, stamped on every vote row
            dataset_repo: optional HF dataset repo (`ns/name`) for durable JSONL backup
            hf_token: optional HF write token used when `dataset_repo` is set
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "votes.db"
        self.jsonl_dir = self.data_dir / "jsonl"
        self.jsonl_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.jsonl_dir / "votes.jsonl"
        # One events file per process boot: the scheduler uploads whole files, so a fresh
        # name per boot means a restart can never overwrite input logs already pushed.
        events_dir = self.jsonl_dir / "events"
        events_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = events_dir / f"events-{uuid.uuid4().hex[:12]}-{os.getpid()}.jsonl"
        self.build_to_contender = dict(build_to_contender)
        self.race_id = race_id
        self._lock = threading.Lock()
        self._scheduler: object | None = None
        self._sync_lock_fh: IO[str] | None = None

        self._init_db()
        if dataset_repo and self._claim_hf_sync_leader():
            # Only sync after a successful restore: pushing a local file that is missing
            # the dataset's history would overwrite every earlier vote.
            if self._hydrate_from_hf(dataset_repo, hf_token):
                self._start_hf_sync(dataset_repo, hf_token)
            else:
                logger.error("Vote sync to %s disabled: could not restore votes", dataset_repo)

    def _claim_hf_sync_leader(self) -> bool:
        """Acquires a non-blocking process lock so only one Uvicorn worker syncs to HF Hub."""
        lock_path = self.data_dir / ".hf_sync.lock"
        fh = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        # Keep the file handle open for the process lifetime so the OS holds the lock.
        self._sync_lock_fh = fh
        return True

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        """Yields a connection inside an IMMEDIATE transaction and always closes it on exit.

        IMMEDIATE takes the write lock up front, so two Uvicorn workers serialize their
        read-then-write sequences (heartbeat credit, vote dedup) instead of racing.
        """
        conn = sqlite3.connect(self.db_path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000;")
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Enables WAL mode and creates or migrates the `sessions`, `votes` and `events` tables."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            # WAL mode persists in the SQLite file header, so setting it once suffices.
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    sid TEXT PRIMARY KEY,
                    a_build TEXT NOT NULL,
                    b_build TEXT NOT NULL,
                    play_a_s REAL NOT NULL DEFAULT 0.0,
                    play_b_s REAL NOT NULL DEFAULT 0.0,
                    last_ping_a REAL NOT NULL DEFAULT 0.0,
                    last_ping_b REAL NOT NULL DEFAULT 0.0,
                    created_at REAL NOT NULL,
                    ip_hash TEXT NOT NULL DEFAULT '',
                    events_logged INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS votes (
                    sid TEXT PRIMARY KEY,
                    race_id TEXT NOT NULL,
                    a_build TEXT NOT NULL,
                    b_build TEXT NOT NULL,
                    a_contender TEXT NOT NULL,
                    b_contender TEXT NOT NULL,
                    slot_picks_json TEXT NOT NULL,
                    contender_picks_json TEXT NOT NULL,
                    play_a_s REAL NOT NULL,
                    play_b_s REAL NOT NULL,
                    submitted_at REAL NOT NULL,
                    ip_hash TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS event_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sid TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    n_events INTEGER NOT NULL,
                    events_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS event_batches_sid ON event_batches (sid);
                """
            )
            # Columns added after the first deploy; ALTER keeps older DBs working. A sibling
            # worker may add the same column first, so a duplicate-column error is fine.
            for table, column, ddl in (
                ("sessions", "ip_hash", "TEXT NOT NULL DEFAULT ''"),
                ("sessions", "events_logged", "INTEGER NOT NULL DEFAULT 0"),
                ("votes", "ip_hash", "TEXT NOT NULL DEFAULT ''"),
            ):
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                    except sqlite3.OperationalError as exc:
                        if "duplicate column" not in str(exc):
                            raise
            conn.execute("CREATE INDEX IF NOT EXISTS sessions_ip ON sessions (ip_hash, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS votes_ip ON votes (ip_hash, submitted_at)")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _is_voted(conn: sqlite3.Connection, sid: str) -> bool:
        """Returns True when `sid` already has a ballot row."""
        return conn.execute("SELECT 1 FROM votes WHERE sid = ?", (sid,)).fetchone() is not None

    @staticmethod
    def _session_state(
        row: sqlite3.Row,
        voted: bool,
        play_a_s: float | None = None,
        play_b_s: float | None = None,
    ) -> SessionState:
        """Builds a `SessionState` from a `sessions` row with optional updated timer values."""
        return SessionState(
            sid=str(row["sid"]),
            a_build=str(row["a_build"]),
            b_build=str(row["b_build"]),
            play_a_s=float(row["play_a_s"]) if play_a_s is None else play_a_s,
            play_b_s=float(row["play_b_s"]) if play_b_s is None else play_b_s,
            voted=voted,
        )

    def ensure_session(
        self,
        sid: str,
        a_build: str,
        b_build: str,
        ip_hash: str = "",
        max_sessions_per_ip: int = 0,
        now: float | None = None,
    ) -> SessionState:
        """Registers a session's blind A/B assignment if new and returns its state.

        Args:
            sid: signed session ID
            a_build: opaque build ID assigned to slot A
            b_build: opaque build ID assigned to slot B
            ip_hash: keyed hash of the client IP, used only for rate limiting
            max_sessions_per_ip: new sessions one IP may open per hour (0 disables)
            now: optional wall-clock timestamp override for deterministic tests

        Returns:
            current `SessionState` including accumulated play seconds and vote flag

        Raises:
            RateLimitedError: if this is a new session and the IP is over its hourly cap
        """
        ts = time.time() if now is None else now
        with self._lock, self._db() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
            if row is None:
                # Cap fresh sessions per IP: each one is a new chance to vote.
                if ip_hash and max_sessions_per_ip > 0:
                    (recent,) = conn.execute(
                        "SELECT COUNT(*) FROM sessions WHERE ip_hash = ? AND created_at > ?",
                        (ip_hash, ts - SESSION_WINDOW_S),
                    ).fetchone()
                    if recent >= max_sessions_per_ip:
                        raise RateLimitedError("too many new sessions from this network")
                conn.execute(
                    """
                    INSERT INTO sessions (sid, a_build, b_build, created_at, ip_hash)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (sid, a_build, b_build, ts, ip_hash),
                )
                row = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
            voted = self._is_voted(conn, sid)
        return self._session_state(row, voted)

    def record_heartbeat(
        self,
        sid: str,
        slot: Literal["a", "b"],
        claimed_seconds: float,
        now: float | None = None,
    ) -> SessionState:
        """Credits verified active play time for one slot with server-side rate limiting.

        Each increment is clamped to `MAX_HEARTBEAT_STEP_S` and to the wall time
        since the session's last heartbeat on *either* slot (or its creation).
        Sharing one clock across both slots means play time accrues at most in
        real time overall: a script can't fill A and B in parallel.

        Args:
            sid: signed session ID (must already be registered via `ensure_session`)
            slot: active blind slot ("a" or "b")
            claimed_seconds: positive seconds elapsed on the client since last ping
            now: optional wall-clock timestamp override for deterministic tests

        Returns:
            updated `SessionState`

        Raises:
            KeyError: if `sid` is unknown
            ValueError: if `slot` is invalid
        """
        if slot not in ("a", "b"):
            raise ValueError(f"invalid slot: {slot!r}")

        ts = time.time() if now is None else now
        clamped_claim = max(0.0, min(float(claimed_seconds), MAX_HEARTBEAT_STEP_S))
        play_col = "play_a_s" if slot == "a" else "play_b_s"
        ping_col = "last_ping_a" if slot == "a" else "last_ping_b"

        with self._lock, self._db() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
            if row is None:
                raise KeyError(f"unknown session: {sid}")

            last_seen = max(
                float(row["last_ping_a"]), float(row["last_ping_b"]), float(row["created_at"])
            )
            elapsed = max(0.0, ts - last_seen)
            credit = min(clamped_claim, elapsed + HEARTBEAT_GRACE_S)

            new_total = round(float(row[play_col]) + credit, 2)
            conn.execute(
                f"UPDATE sessions SET {play_col} = ?, {ping_col} = ? WHERE sid = ?",
                (new_total, ts, sid),
            )
            voted = self._is_voted(conn, sid)

        return self._session_state(
            row,
            voted,
            play_a_s=new_total if slot == "a" else None,
            play_b_s=new_total if slot == "b" else None,
        )

    def submit_vote(
        self,
        sid: str,
        slot_picks: dict[str, str],
        min_play_seconds: float,
        ip_hash: str = "",
        max_votes_per_ip: int = 0,
    ) -> VoteSummary:
        """Validates play-time gates and records a de-blinded pairwise ballot.

        Args:
            sid: signed session ID
            slot_picks: mapping of each question in `QUESTIONS` to `"a"`, `"b"`, or `"tie"`
            min_play_seconds: minimum active seconds required in *each* build before voting
            ip_hash: keyed hash of the client IP, used only for rate limiting
            max_votes_per_ip: ballots one IP may cast per day (0 disables)

        Returns:
            the persisted `VoteSummary` including de-blinded contender mappings

        Raises:
            KeyError: if `sid` is not registered
            ValueError: if picks are malformed, play time is below gate, or already voted
            RateLimitedError: if the IP has hit its daily ballot cap
        """
        normalized: dict[str, str] = {}
        for q in QUESTIONS:
            val = str(slot_picks.get(q, "")).strip().lower()
            if val not in VALID_PICKS:
                raise ValueError(f"question '{q}' must be 'a', 'b', or 'tie'")
            normalized[q] = val

        now = time.time()
        with self._lock, self._db() as conn:
            sess = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
            if sess is None:
                raise KeyError(f"unknown session: {sid}")
            if self._is_voted(conn, sid):
                raise ValueError("this session has already voted")

            play_a = float(sess["play_a_s"])
            play_b = float(sess["play_b_s"])
            if play_a < min_play_seconds or play_b < min_play_seconds:
                raise ValueError(
                    f"play at least {int(min_play_seconds)}s in both Build A "
                    f"({int(play_a)}s) and Build B ({int(play_b)}s) before voting"
                )

            if ip_hash and max_votes_per_ip > 0:
                (recent,) = conn.execute(
                    "SELECT COUNT(*) FROM votes WHERE ip_hash = ? AND submitted_at > ?",
                    (ip_hash, now - VOTE_WINDOW_S),
                ).fetchone()
                if recent >= max_votes_per_ip:
                    raise RateLimitedError("this network has reached today's vote limit")

            a_build = str(sess["a_build"])
            b_build = str(sess["b_build"])
            a_contender = self.build_to_contender[a_build]
            b_contender = self.build_to_contender[b_build]

            # Translate slot-relative picks ("a"/"b"/"tie") into true contenders server-side.
            contender_picks = {
                q: (a_contender if pick == "a" else b_contender if pick == "b" else "tie")
                for q, pick in normalized.items()
            }

            cur = conn.execute(
                _INSERT_VOTE_SQL,
                (
                    sid,
                    self.race_id,
                    a_build,
                    b_build,
                    a_contender,
                    b_contender,
                    json.dumps(normalized, sort_keys=True),
                    json.dumps(contender_picks, sort_keys=True),
                    play_a,
                    play_b,
                    now,
                    ip_hash,
                ),
            )
            if cur.rowcount != 1:
                raise ValueError("this session has already voted")

            summary: VoteSummary = {
                "sid": sid,
                "a_build": a_build,
                "b_build": b_build,
                "a_contender": a_contender,
                "b_contender": b_contender,
                "slot_picks": normalized,
                "contender_picks": contender_picks,
                "play_a_s": play_a,
                "play_b_s": play_b,
                "submitted_at": now,
            }
            _append_locked(
                self.jsonl_path,
                json.dumps({"race_id": self.race_id, "ip_hash": ip_hash, **summary}, sort_keys=True)
                + "\n",
            )

        return summary

    def record_events(
        self,
        sid: str,
        slot: Literal["a", "b"],
        events: Sequence[Sequence[object]],
        now: float | None = None,
    ) -> int:
        """Stores one batch of input events (keys, mouse buttons, focus) for a session slot.

        Each batch is written to SQLite and mirrored as one JSONL line that carries
        the de-blinded contender and the slot's server-verified play time, so the
        synced dataset can be analysed without the manifest or the session table.

        Args:
            sid: signed session ID (must already be registered via `ensure_session`)
            slot: blind slot ("a" or "b") the events came from
            events: `[t_ms, kind, code]` triples, already validated by the API layer
            now: optional wall-clock timestamp override for deterministic tests

        Returns:
            number of events stored (0 once the session hits `MAX_EVENTS_PER_SESSION`)

        Raises:
            KeyError: if `sid` is unknown
        """
        ts = time.time() if now is None else now
        with self._lock, self._db() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
            if row is None:
                raise KeyError(f"unknown session: {sid}")
            room = MAX_EVENTS_PER_SESSION - int(row["events_logged"])
            kept = [list(e) for e in events[: max(0, room)]]
            if not kept:
                return 0

            build = str(row["a_build"] if slot == "a" else row["b_build"])
            events_json = json.dumps(kept, separators=(",", ":"))
            conn.execute(
                """
                INSERT INTO event_batches (sid, slot, received_at, n_events, events_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, slot, ts, len(kept), events_json),
            )
            conn.execute(
                "UPDATE sessions SET events_logged = events_logged + ? WHERE sid = ?",
                (len(kept), sid),
            )
            record = {
                "race_id": self.race_id,
                "sid": sid,
                "slot": slot,
                "build": build,
                "contender": self.build_to_contender.get(build, ""),
                "received_at": ts,
                "play_s": float(row["play_a_s"] if slot == "a" else row["play_b_s"]),
                "events": kept,
            }
            _append_locked(self.events_path, json.dumps(record, separators=(",", ":")) + "\n")
        return len(kept)

    def get_vote(self, sid: str) -> VoteSummary | None:
        """Returns a session's submitted ballot if one exists, else None."""
        with self._lock, self._db() as conn:
            row = conn.execute("SELECT * FROM votes WHERE sid = ?", (sid,)).fetchone()
        if row is None:
            return None
        return {
            "sid": str(row["sid"]),
            "a_build": str(row["a_build"]),
            "b_build": str(row["b_build"]),
            "a_contender": str(row["a_contender"]),
            "b_contender": str(row["b_contender"]),
            "slot_picks": json.loads(str(row["slot_picks_json"])),
            "contender_picks": json.loads(str(row["contender_picks_json"])),
            "play_a_s": float(row["play_a_s"]),
            "play_b_s": float(row["play_b_s"]),
            "submitted_at": float(row["submitted_at"]),
        }

    def tallies(self) -> dict[str, object]:
        """Aggregates de-blinded community votes for the current race across all four questions.

        Returns:
            dict with `total_ballots` and `questions` (per-question contender + tie counts)
        """
        contenders = sorted(set(self.build_to_contender.values()))
        per_q: dict[str, QuestionTally] = {
            q: {"counts": {c: 0 for c in (*contenders, "tie")}, "total": 0} for q in QUESTIONS
        }
        # Filter by race: the vote dataset outlives a deploy, so old races' ballots stay in it.
        with self._lock, self._db() as conn:
            rows = conn.execute(
                "SELECT contender_picks_json FROM votes WHERE race_id = ?", (self.race_id,)
            ).fetchall()

        for row in rows:
            picks = json.loads(str(row["contender_picks_json"]))
            for q in QUESTIONS:
                winner = picks.get(q)
                if winner in per_q[q]["counts"]:
                    per_q[q]["counts"][winner] += 1
                    per_q[q]["total"] += 1

        return {"total_ballots": len(rows), "questions": per_q}

    def _rewrite_votes_jsonl(self) -> None:
        """Regenerates `votes.jsonl` from every ballot in SQLite (restored plus local).

        Holds the file lock while reading the DB and rewriting, so a vote appended by
        another worker either lands in the rewrite or is appended after it.
        """
        with self.jsonl_path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                with self._db() as conn:
                    rows = conn.execute("SELECT * FROM votes ORDER BY submitted_at").fetchall()
                fh.seek(0)
                fh.truncate()
                for row in rows:
                    rec = {
                        "race_id": str(row["race_id"]),
                        "ip_hash": str(row["ip_hash"]),
                        "sid": str(row["sid"]),
                        "a_build": str(row["a_build"]),
                        "b_build": str(row["b_build"]),
                        "a_contender": str(row["a_contender"]),
                        "b_contender": str(row["b_contender"]),
                        "slot_picks": json.loads(str(row["slot_picks_json"])),
                        "contender_picks": json.loads(str(row["contender_picks_json"])),
                        "play_a_s": float(row["play_a_s"]),
                        "play_b_s": float(row["play_b_s"]),
                        "submitted_at": float(row["submitted_at"]),
                    }
                    fh.write(json.dumps(rec, sort_keys=True) + "\n")
                fh.flush()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _hydrate_from_hf(self, dataset_repo: str, hf_token: str | None) -> bool:
        """Restores historical votes from a HF Dataset JSONL file into SQLite on boot.

        Returns:
            True when the dataset's votes are restored (or it has none yet), so syncing
            is safe; False when the download failed and syncing would lose history
        """
        try:
            from huggingface_hub import hf_hub_download
            from huggingface_hub.errors import RemoteEntryNotFoundError
        except ImportError:
            logger.warning("huggingface_hub not installed; skipping HF vote hydration")
            return False

        try:
            downloaded = Path(
                hf_hub_download(
                    repo_id=dataset_repo,
                    repo_type="dataset",
                    filename="votes.jsonl",
                    token=hf_token,
                )
            )
        except RemoteEntryNotFoundError:
            # Only a confirmed-missing file on the Hub means "no history". Offline
            # (LocalEntryNotFoundError), auth or missing-repo errors fall through to False.
            logger.info("No existing votes.jsonl in %s; starting fresh", dataset_repo)
            self._rewrite_votes_jsonl()
            return True
        except Exception as exc:  # noqa: BLE001 - network issues must not block Space boot
            logger.warning("Failed to hydrate votes from %s: %s", dataset_repo, exc)
            return False

        imported = 0
        with self._lock, self._db() as conn:
            for line in downloaded.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    conn.execute(
                        _INSERT_VOTE_SQL,
                        (
                            rec["sid"],
                            # Legacy rows get "unknown", never this race, so they skip tallies.
                            rec.get("race_id") or "unknown",
                            rec["a_build"],
                            rec["b_build"],
                            rec["a_contender"],
                            rec["b_contender"],
                            json.dumps(rec["slot_picks"], sort_keys=True),
                            json.dumps(rec["contender_picks"], sort_keys=True),
                            float(rec.get("play_a_s", 0.0)),
                            float(rec.get("play_b_s", 0.0)),
                            float(rec.get("submitted_at", 0.0)),
                            str(rec.get("ip_hash", "")),
                        ),
                    )
                    imported += 1
                except (KeyError, ValueError, TypeError):
                    continue
        # Rebuild the local file from the DB so the next push is the union of remote
        # history and any votes this container already held.
        self._rewrite_votes_jsonl()
        logger.info("Hydrated %d votes from %s", imported, dataset_repo)
        return True

    def _start_hf_sync(self, dataset_repo: str, hf_token: str | None) -> None:
        """Starts a background CommitScheduler to push the JSONL folder every 2 minutes."""
        try:
            from huggingface_hub import CommitScheduler
        except ImportError:
            logger.warning("huggingface_hub not installed; skipping HF vote sync")
            return

        try:
            self._scheduler = CommitScheduler(
                repo_id=dataset_repo,
                repo_type="dataset",
                folder_path=self.jsonl_dir,
                every=2,
                token=hf_token,
                private=True,
            )
            logger.info("Started HF CommitScheduler syncing votes to %s", dataset_repo)
        except Exception as exc:  # noqa: BLE001 - keep local voting alive even if Hub fails
            logger.warning("Could not start HF CommitScheduler for %s: %s", dataset_repo, exc)
