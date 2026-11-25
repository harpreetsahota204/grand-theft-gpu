"""FastAPI server for the Grand Theft GPU blind play-and-vote Hugging Face Space.

Serves two mystery Three.js builds behind opaque `/play/a/` and `/play/b/` routes
using a server-signed, 50/50 counterbalanced session cookie (`arena.blind`),
tracks verified play time per build, and stores pairwise ballots in SQLite plus
an optional Hugging Face Dataset backup (`arena.storage`).

Start locally from the repo root:
    uv run --with fastapi --with "uvicorn[standard]" uvicorn app:app --app-dir arena --port 7860
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
from pathlib import Path
from typing import Annotated, Literal

from blind import (
    SessionPayload,
    Slot,
    inject_slot_shim,
    new_session,
    shared_asset_cdn_url,
    sign_session,
    verify_session,
)
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, StringConstraints
from storage import QUESTIONS, RateLimitedError, SessionState, VoteStore, VoteSummary

logger = logging.getLogger("uvicorn.error")

APP_DIR: Path = Path(__file__).resolve().parent
BUILDS_DIR: Path = Path(os.environ.get("ARENA_BUILDS_DIR", APP_DIR / "builds")).resolve()
DATA_DIR: Path = Path(os.environ.get("ARENA_DATA_DIR", APP_DIR / "data")).resolve()
STATIC_DIR: Path = APP_DIR / "static"


def _load_session_secret(data_dir: Path) -> str:
    """Loads `ARENA_SECRET` or creates a shared container-local key for multi-worker uvicorn."""
    env_secret = os.environ.get("ARENA_SECRET", "").strip()
    if env_secret:
        return env_secret
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file = data_dir / ".session_secret"
    # Write the key to a private temp file, then hard-link it into place: the link is
    # atomic and fails if the file exists, so a sibling worker never reads a half-written
    # key, and every worker ends up with the same one.
    tmp = data_dir / f".session_secret.{os.getpid()}.{secrets.token_hex(4)}"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secrets.token_hex(32))
    try:
        os.link(tmp, secret_file)
    except FileExistsError:
        pass
    finally:
        tmp.unlink(missing_ok=True)
    return secret_file.read_text(encoding="utf-8").strip()


# Signing secret for HttpOnly session cookies; override via Space Secret in production.
SESSION_SECRET: str = _load_session_secret(DATA_DIR)
MIN_PLAY_SECONDS: float = float(os.environ.get("MIN_PLAY_SECONDS", "60"))
REVEAL_ON_VOTE: bool = os.environ.get("REVEAL_ON_VOTE", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)
VOTE_DATASET_REPO: str = os.environ.get("VOTE_DATASET_REPO", "").strip()
HF_TOKEN: str | None = os.environ.get("HF_TOKEN") or None
# Per-IP caps against ballot stuffing (0 disables). Generous enough for a shared office or
# conference network; a script still needs a real ~2 min of play per ballot on top.
MAX_SESSIONS_PER_IP_PER_HOUR: int = int(os.environ.get("MAX_SESSIONS_PER_IP_PER_HOUR", "30"))
MAX_VOTES_PER_IP_PER_DAY: int = int(os.environ.get("MAX_VOTES_PER_IP_PER_DAY", "20"))
# Proxies in front of the app that append to X-Forwarded-For; the client IP is the entry
# this many places from the right. Check the startup log line on a deployed Space.
TRUSTED_PROXY_HOPS: int = max(1, int(os.environ.get("TRUSTED_PROXY_HOPS", "1")))
# Largest POST body accepted on /api/* (an events batch is ~40 KB at its 1,000-event cap).
MAX_API_BODY_BYTES: int = 256 * 1024

SESSION_COOKIE: str = "gtgpu_arena_session"
SESSION_HEADER: str = "x-arena-token"
ACTIVE_SLOT_COOKIE: str = "gtgpu_active_slot"

# Matches `/s/{token}/play/{a|b}/...` or `/play/{a|b}/...` in HTTP Referer headers.
_REFERER_SLOT_RE: re.Pattern[str] = re.compile(
    r"(?:/s/([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+))?/play/(a|b)/"
)


class HeartbeatRequest(BaseModel):
    """Payload sent periodically by the arena UI while a player plays slot A or B."""

    slot: Slot
    seconds: float = 15.0


# Input event kinds the injected logger sends (`blind.build_input_logger_script`).
EventKind = Literal[
    "start", "kd", "ku", "md", "mu", "lock", "unlock", "focus", "blur", "hidden", "visible", "exit"
]


class EventsRequest(BaseModel):
    """One batch of input events posted by the logger inside a Build A/B iframe."""

    token: str | None = Field(default=None, max_length=512)
    slot: Slot
    # `[ms_since_page_load, kind, code]`; code is a KeyboardEvent.code, button number or ''.
    events: list[tuple[float, EventKind, Annotated[str, StringConstraints(max_length=32)]]] = Field(
        max_length=1000
    )


class VoteRequest(BaseModel):
    """Pairwise ballot covering the four locked questions in `scoring/checklist.md`."""

    plays_better: Literal["a", "b", "tie"]
    looks_better: Literal["a", "b", "tie"]
    better_main_character: Literal["a", "b", "tie"]
    overall: Literal["a", "b", "tie"]


class ArenaRuntime:
    """Loaded manifest metadata and vote store for the running Space process.

    Created once at import time. If `builds/manifest.json` does not exist yet,
    `ready` stays False so the UI displays setup instructions instead of crashing.
    """

    def __init__(self) -> None:
        """Loads manifest from `ARENA_MANIFEST_JSON` or `builds/manifest.json`."""
        manifest_path = BUILDS_DIR / "manifest.json"
        self.ready: bool = False
        self.race_id: str = ""
        self.hf_assets_repo: str = ""
        self.hf_assets_revision: str = ""
        self.build_ids: tuple[str, str] | None = None
        self.build_to_contender: dict[str, str] = {}
        self.contender_labels: dict[str, str] = {}
        self.store: VoteStore | None = None

        # Prefer ARENA_MANIFEST_JSON Space secret so public repos never expose the mapping.
        manifest_env = os.environ.get("ARENA_MANIFEST_JSON", "").strip()
        if manifest_env:
            data = json.loads(manifest_env)
        elif manifest_path.exists():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            return
        builds = data.get("builds", {})
        if not isinstance(builds, dict) or len(builds) != 2:
            return

        ids = sorted(builds.keys())
        self.build_ids = (ids[0], ids[1])
        self.race_id = str(data.get("race_id", ""))
        self.hf_assets_repo = str(data.get("hf_assets_repo", ""))
        self.hf_assets_revision = str(data.get("hf_assets_revision", ""))
        for bid, info in builds.items():
            contender = str(info["contender"])
            self.build_to_contender[bid] = contender
            self.contender_labels[contender] = str(info.get("label", contender))

        self.store = VoteStore(
            data_dir=DATA_DIR,
            build_to_contender=self.build_to_contender,
            race_id=self.race_id,
            dataset_repo=VOTE_DATASET_REPO,
            hf_token=HF_TOKEN,
        )
        self.ready = True


runtime = ArenaRuntime()
app = FastAPI(title="Grand Theft GPU — Blind Arena", docs_url=None, redoc_url=None)


@app.middleware("http")
async def limit_api_body(request: Request, call_next):  # noqa: ANN001, ANN201
    """Rejects oversized or unsized POST bodies on `/api/*` before they are read."""
    if request.method == "POST" and request.url.path.startswith("/api/"):
        length = request.headers.get("content-length")
        if length is None or not length.isdigit() or int(length) > MAX_API_BODY_BYTES:
            return Response(status_code=413, content="Request body too large or unsized")
    return await call_next(request)


def _safe_resolve(root: Path, rel_path: str) -> Path | None:
    """Resolves `rel_path` strictly inside `root`, returning None on traversal attempts."""
    candidate = (root / rel_path.lstrip("/")).resolve()
    root_resolved = root.resolve()
    if not candidate.is_relative_to(root_resolved):
        return None
    return candidate


def _is_https(request: Request) -> bool:
    """Returns True when the request arrived over HTTPS (including reverse proxies)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.lower() == "https"


_proxy_chain_logged: bool = False


def _log_proxy_chain_once(hops: list[str]) -> None:
    """Logs the X-Forwarded-For shape once per worker (no addresses) to tune proxy hops."""
    global _proxy_chain_logged
    if _proxy_chain_logged:
        return
    _proxy_chain_logged = True

    def _kind(hop: str) -> str:
        """Classifies one hop as public, private or unparseable without revealing it."""
        try:
            return "private" if ipaddress.ip_address(hop).is_private else "public"
        except ValueError:
            return "invalid"

    logger.info(
        "X-Forwarded-For has %d hop(s): %s (TRUSTED_PROXY_HOPS=%d)",
        len(hops),
        ",".join(_kind(h) for h in hops) or "none",
        TRUSTED_PROXY_HOPS,
    )


def _client_ip_hash(request: Request) -> str:
    """Returns a keyed hash of the client IP for rate limiting; the raw IP is never stored.

    Uses the right-most `X-Forwarded-For` entry, the one added by the Space's own proxy;
    entries to its left are client-supplied and trivially spoofed.
    """
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    _log_proxy_chain_once(hops)
    ip = hops[-TRUSTED_PROXY_HOPS] if len(hops) >= TRUSTED_PROXY_HOPS else ""
    if not ip and request.client is not None:
        ip = request.client.host
    if not ip:
        return ""
    return hmac.new(SESSION_SECRET.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def _resolve_cookie(
    request: Request, explicit_token: str | None = None
) -> tuple[SessionPayload, str, bool]:
    """Reads or mints a signed blind A/B session token with zero database I/O.

    Checks `explicit_token` (path segment), then `X-Arena-Token` header, then the
    HttpOnly cookie. Supporting header/path tokens keeps blind A/B assignments
    sticky inside cross-site iframes (such as huggingface.co -> *.hf.space) where
    browsers block third-party cookies.

    Args:
        request: incoming FastAPI request
        explicit_token: optional signed token extracted from the URL path

    Returns:
        tuple of `(payload, token, minted)` where `minted` is True if a new session
        was generated on this request

    Raises:
        HTTPException: 503 if builds have not been packaged into `arena/builds/`
    """
    if not runtime.ready or runtime.build_ids is None:
        raise HTTPException(status_code=503, detail="Arena builds not packaged yet.")

    valid_ids = set(runtime.build_ids)
    for candidate in (
        explicit_token,
        request.headers.get(SESSION_HEADER),
        request.cookies.get(SESSION_COOKIE),
    ):
        payload = verify_session(candidate, SESSION_SECRET, valid_ids)
        if payload is not None and candidate is not None:
            return payload, candidate, False

    fresh = new_session(runtime.build_ids, SESSION_SECRET)
    return fresh, sign_session(fresh, SESSION_SECRET), True


def _resolve_session(
    request: Request,
) -> tuple[SessionPayload, SessionState, str, bool, VoteStore]:
    """Resolves the signed token and ensures the corresponding SQLite session row exists.

    Args:
        request: incoming FastAPI request

    Returns:
        tuple of `(payload, state, token, minted, store)`

    Raises:
        HTTPException: 503 if builds have not been packaged into `arena/builds/`
    """
    if runtime.store is None:
        raise HTTPException(status_code=503, detail="Arena builds not packaged yet.")

    payload, token, minted = _resolve_cookie(request)
    try:
        state = runtime.store.ensure_session(
            payload["sid"],
            payload["order"][0],
            payload["order"][1],
            ip_hash=_client_ip_hash(request),
            max_sessions_per_ip=MAX_SESSIONS_PER_IP_PER_HOUR,
        )
    except RateLimitedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    return payload, state, token, minted, runtime.store


def _can_vote(state: SessionState) -> bool:
    """Returns True when the session has not voted and met the play gate on both slots."""
    return (
        not state.voted
        and state.play_a_s >= MIN_PLAY_SECONDS
        and state.play_b_s >= MIN_PLAY_SECONDS
    )


def _attach_session_cookie(request: Request, response: Response, token: str, minted: bool) -> None:
    """Sets the signed HttpOnly cookie when newly minted (`SameSite=None` on HTTPS)."""
    if not minted:
        return
    secure = _is_https(request)
    # Use SameSite=None + Secure on HTTPS so HF Space iframes accept cookies when allowed.
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
        max_age=60 * 60 * 24 * 30,
    )


def _slot_build_dir(payload: SessionPayload, slot: Slot) -> Path:
    """Returns the filesystem root directory for the visitor's assigned slot A or B."""
    build_id = payload["order"][0] if slot == "a" else payload["order"][1]
    return (BUILDS_DIR / build_id).resolve()


def _file_response(target: Path, cache_control: str) -> FileResponse:
    """Builds a `FileResponse` with guessed MIME type and explicit `Cache-Control`."""
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": cache_control},
    )


def _serve_build_file(build_dir: Path, rel_path: str) -> FileResponse:
    """Serves one static file strictly inside `build_dir`, or raises 404."""
    target = _safe_resolve(build_dir, rel_path)
    if target is None or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return _file_response(target, "private, max-age=3600")


def _build_reveal(vote: VoteSummary, store: VoteStore) -> dict[str, object] | None:
    """Constructs the post-vote reveal payload, or None when reveals are withheld."""
    if not REVEAL_ON_VOTE:
        return None
    return {
        "a_contender": vote["a_contender"],
        "b_contender": vote["b_contender"],
        "a_label": runtime.contender_labels.get(vote["a_contender"], vote["a_contender"]),
        "b_label": runtime.contender_labels.get(vote["b_contender"], vote["b_contender"]),
        "slot_picks": vote["slot_picks"],
        "contender_picks": vote["contender_picks"],
        "labels": runtime.contender_labels,
        "tallies": store.tallies(),
    }


def _serve_shared_asset(rel_path: str) -> Response:
    """Serves a shared `assets/gt-gpu/` file locally if linked, else redirects to HF CDN."""
    local_shared = BUILDS_DIR / "_shared_assets"
    if local_shared.exists():
        target = _safe_resolve(local_shared, rel_path)
        if target is not None and target.is_file():
            return _file_response(target, "public, max-age=86400")
    if not runtime.hf_assets_repo or not runtime.hf_assets_revision:
        raise HTTPException(status_code=404, detail="Shared asset store not configured")
    cdn_url = shared_asset_cdn_url(rel_path, runtime.hf_assets_repo, runtime.hf_assets_revision)
    return RedirectResponse(url=cdn_url, status_code=302)


@app.get("/health")
def health() -> dict[str, object]:
    """Reports container liveness and whether opaque builds are packaged."""
    return {"status": "ok", "builds_ready": runtime.ready, "race_id": runtime.race_id}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    """Serves the blind arena shell page and mints a cookie when builds are ready."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    resp = HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
    if runtime.ready:
        _, token, minted = _resolve_cookie(request)
        _attach_session_cookie(request, resp, token, minted)
    return resp


@app.get("/api/session")
def api_session(request: Request, response: Response) -> dict[str, object]:
    """Returns signed opaque token, play timers, vote gate, and post-vote reveal."""
    response.headers["Cache-Control"] = "no-store"
    if not runtime.ready:
        return {"builds_ready": False, "min_play_seconds": MIN_PLAY_SECONDS}

    payload, state, token, minted, store = _resolve_session(request)
    _attach_session_cookie(request, response, token, minted)
    vote = store.get_vote(payload["sid"]) if state.voted else None
    return {
        "builds_ready": True,
        "token": token,
        "voted": state.voted,
        "min_play_seconds": MIN_PLAY_SECONDS,
        "play_seconds": {"a": round(state.play_a_s, 1), "b": round(state.play_b_s, 1)},
        "can_vote": _can_vote(state),
        "reveal_enabled": REVEAL_ON_VOTE,
        "reveal": _build_reveal(vote, store) if vote is not None else None,
        "questions": list(QUESTIONS),
    }


@app.post("/api/heartbeat")
def api_heartbeat(
    body: HeartbeatRequest, request: Request, response: Response
) -> dict[str, object]:
    """Records verified active play time for the currently open build slot."""
    payload, _, token, minted, store = _resolve_session(request)
    _attach_session_cookie(request, response, token, minted)
    state = store.record_heartbeat(payload["sid"], body.slot, body.seconds)
    return {
        "play_seconds": {"a": round(state.play_a_s, 1), "b": round(state.play_b_s, 1)},
        "can_vote": _can_vote(state),
        "voted": state.voted,
    }


@app.post("/api/vote")
def api_vote(body: VoteRequest, request: Request, response: Response) -> dict[str, object]:
    """Validates play-time requirements, stores the de-blinded ballot, and returns reveal."""
    payload, _, token, minted, store = _resolve_session(request)
    _attach_session_cookie(request, response, token, minted)
    try:
        summary = store.submit_vote(
            sid=payload["sid"],
            slot_picks=body.model_dump(),
            min_play_seconds=MIN_PLAY_SECONDS,
            ip_hash=_client_ip_hash(request),
            max_votes_per_ip=MAX_VOTES_PER_IP_PER_DAY,
        )
    except RateLimitedError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "ok": True,
        "reveal_enabled": REVEAL_ON_VOTE,
        "reveal": _build_reveal(summary, store),
    }


@app.post("/api/events")
def api_events(body: EventsRequest, request: Request) -> dict[str, object]:
    """Stores one batch of input events from the logger injected into a build iframe.

    Never mints a session: a batch with no valid token or cookie is dropped, so the
    logger can't create sessions that bypass the per-IP cap.
    """
    if runtime.store is None or runtime.build_ids is None:
        raise HTTPException(status_code=503, detail="Arena builds not packaged yet.")
    payload, _, minted = _resolve_cookie(request, explicit_token=body.token)
    if minted:
        raise HTTPException(status_code=401, detail="No arena session")
    try:
        stored = runtime.store.record_events(payload["sid"], body.slot, body.events)
    except KeyError:
        raise HTTPException(status_code=401, detail="Unknown arena session") from None
    return {"stored": stored}


@app.get("/play/{slot}")
def play_redirect(slot: Slot) -> RedirectResponse:
    """Normalizes `/play/a` to `/play/a/` so relative URLs resolve inside the slot."""
    return RedirectResponse(url=f"/play/{slot}/", status_code=307)


def _render_play_entry(slot: Slot, request: Request, explicit_token: str | None = None) -> Response:
    """Renders the blind Build A or Build B `index.html` bound to the session token."""
    payload, token, minted = _resolve_cookie(request, explicit_token=explicit_token)
    build_dir = _slot_build_dir(payload, slot)
    entry = build_dir / "index.html"
    if not entry.is_file():
        raise HTTPException(status_code=404, detail="Build entry missing")

    raw_html = entry.read_text(encoding="utf-8")
    resp = HTMLResponse(
        content=inject_slot_shim(raw_html, slot, token=token),
        headers={"Cache-Control": "no-store"},
    )
    _attach_session_cookie(request, resp, token, minted)
    secure = _is_https(request)
    resp.set_cookie(
        key=ACTIVE_SLOT_COOKIE,
        value=slot,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
    )
    return resp


@app.get("/play/{slot}/", response_class=HTMLResponse)
def play_entry(slot: Slot, request: Request) -> Response:
    """Serves Build A or Build B via cookie-backed route."""
    return _render_play_entry(slot, request)


@app.get("/s/{token}/play/{slot}/", response_class=HTMLResponse)
def play_entry_tokenized(token: str, slot: Slot, request: Request) -> Response:
    """Serves Build A or Build B via cookieless path-tokenized route (HF Space iframes)."""
    return _render_play_entry(slot, request, explicit_token=token)


@app.get("/s/{token}/play/{slot}/assets/gt-gpu/{rel_path:path}")
def play_tokenized_shared_asset(token: str, slot: Slot, rel_path: str) -> Response:
    """Routes tokenized shared asset requests to local symlink or HF dataset CDN."""
    del slot, token  # Shared assets are byte-identical across both contenders.
    return _serve_shared_asset(rel_path)


@app.get("/play/{slot}/assets/gt-gpu/{rel_path:path}")
def play_shared_asset(slot: Slot, rel_path: str) -> Response:
    """Routes slot-prefixed shared asset requests to local symlink or HF dataset CDN."""
    del slot  # Shared assets are byte-identical across both contenders.
    return _serve_shared_asset(rel_path)


@app.get("/assets/gt-gpu/{rel_path:path}")
def root_shared_asset(rel_path: str) -> Response:
    """Routes root-relative `/assets/gt-gpu/...` requests to local symlink or HF dataset CDN."""
    return _serve_shared_asset(rel_path)


@app.get("/s/{token}/play/{slot}/{rel_path:path}")
def play_tokenized_asset(token: str, slot: Slot, rel_path: str, request: Request) -> Response:
    """Serves build-specific static assets bound to the path token (no cookie required)."""
    payload, resolved_token, minted = _resolve_cookie(request, explicit_token=token)
    resp = _serve_build_file(_slot_build_dir(payload, slot), rel_path)
    _attach_session_cookie(request, resp, resolved_token, minted)
    return resp


@app.get("/play/{slot}/{rel_path:path}")
def play_asset(slot: Slot, rel_path: str, request: Request) -> Response:
    """Serves build-specific static assets for the visitor's blind slot A or B."""
    payload, token, minted = _resolve_cookie(request)
    resp = _serve_build_file(_slot_build_dir(payload, slot), rel_path)
    _attach_session_cookie(request, resp, token, minted)
    return resp


@app.get("/assets/{rel_path:path}")
def root_asset_fallback(rel_path: str, request: Request) -> Response:
    """Fallback for root-relative `/assets/...` requests that bypass the inline JS shim.

    Extracts `(token, slot)` from the HTTP `Referer` header first, falling back
    to the active-slot cookie when Referer is absent, then redirects to the
    slot's tokenized asset URL.
    """
    referer = request.headers.get("referer", "")
    match = _REFERER_SLOT_RE.search(referer)
    ref_token = match.group(1) if match else None
    raw_slot = match.group(2) if match else request.cookies.get(ACTIVE_SLOT_COOKIE, "")
    if raw_slot not in ("a", "b"):
        raise HTTPException(status_code=404, detail="No active build slot")

    payload, token, minted = _resolve_cookie(request, explicit_token=ref_token)
    slot: Slot = "a" if raw_slot == "a" else "b"
    if _safe_resolve(_slot_build_dir(payload, slot), f"assets/{rel_path}") is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    # Redirect instead of serving: this URL is the same for both slots, so a cached body
    # could hand Build B a file from Build A. The tokenized URL is unique per slot.
    target = f"/s/{token}/play/{slot}/assets/{rel_path}"
    if request.url.query:
        target += f"?{request.url.query}"
    resp = RedirectResponse(url=target, status_code=307, headers={"Cache-Control": "no-store"})
    _attach_session_cookie(request, resp, token, minted)
    return resp
