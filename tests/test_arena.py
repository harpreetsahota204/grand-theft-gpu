"""Unit tests for the blind play-and-vote Hugging Face Space (`arena/`).

Covers pure-Python blinding, cookie signing, HTML asset-shim rewriting,
anti-spoof heartbeat rate limiting, vote de-blinding and deduplication, and
the `prepare.py` packager + identity leak scanner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make `arena/` modules importable directly, matching how `uvicorn app:app --app-dir arena` runs.
ARENA_DIR: Path = Path(__file__).resolve().parent.parent / "arena"
# Appended, not prepended, so arena's generic module names (`app`, `storage`) never
# shadow a same-named module for the rest of the pytest session.
if str(ARENA_DIR) not in sys.path:
    sys.path.append(str(ARENA_DIR))

import blind  # noqa: E402
import prepare  # noqa: E402
import storage  # noqa: E402


def test_session_cookie_round_trip_and_tamper_rejection() -> None:
    """Valid tokens decode cleanly; tampered or other-race tokens are rejected."""
    build_ids = ("b-1111aaaa", "b-2222bbbb")
    secret = "test-secret-key"
    payload = blind.new_session(build_ids, secret)

    assert set(payload["order"]) == set(build_ids)
    token = blind.sign_session(payload, secret)
    decoded = blind.verify_session(token, secret, set(build_ids))
    assert decoded == payload

    # Wrong secret, modified signature, or another race's build pair must all fail closed.
    assert blind.verify_session(token, "wrong-secret", set(build_ids)) is None
    assert blind.verify_session(token[:-1] + "X", secret, set(build_ids)) is None
    assert blind.verify_session(token, secret, {"b-other1", "b-other2"}) is None
    assert blind.verify_session(None, secret, set(build_ids)) is None


def test_token_never_reveals_slot_order() -> None:
    """The token carries only the sid; the A/B order is secret yet counterbalanced."""
    import base64

    build_ids = ("b-1111aaaa", "b-2222bbbb")
    orders = []
    for _ in range(400):
        payload = blind.new_session(build_ids, "k")
        token = blind.sign_session(payload, "k")
        body = token.split(".")[0]
        decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
        assert "b-1111aaaa" not in decoded and "b-2222bbbb" not in decoded
        assert json.loads(decoded) == {"sid": payload["sid"]}
        orders.append(payload["order"][0])
    # Roughly 50/50 across sessions (400 draws: well inside 150..250).
    assert 150 < orders.count("b-1111aaaa") < 250
    # A different secret gives an unrelated order for the same sid.
    sid = "f" * 32
    flips = {tuple(blind.slot_order(sid, build_ids, f"key-{i}")) for i in range(20)}
    assert len(flips) == 2


def test_old_format_tokens_are_rejected() -> None:
    """Pre-fix tokens that spelled out the order get a fresh session, not a mismatch."""
    import base64

    ids = ["b-1111aaaa", "b-2222bbbb"]
    raw = json.dumps({"order": ids, "sid": "a" * 32}, separators=(",", ":"), sort_keys=True)
    body = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    token = f"{body}.{blind._sign_body(body, 'k', ids)}"
    assert blind.verify_session(token, "k", set(ids)) is None


def test_inject_slot_shim_rewrites_static_tags_and_inserts_shim() -> None:
    """Vite `/assets/` links route to `/play/{slot}/assets/` and shared assets stay unprefixed."""
    raw = (
        "<!doctype html><html><head>"
        '<script type="module" src="/assets/index-123.js"></script>'
        '<link rel="stylesheet" href="/assets/index-123.css">'
        "</head><body></body></html>"
    )
    out = blind.inject_slot_shim(raw, "b", token="tok.sig")
    assert 'src="/s/tok.sig/play/b/assets/index-123.js"' in out
    assert 'href="/s/tok.sig/play/b/assets/index-123.css"' in out
    assert 'var P="/s/tok.sig/play/b/assets/",S="/assets/gt-gpu/"' in out
    assert out.index("<script>(function()") < out.index(
        'src="/s/tok.sig/play/b/assets/index-123.js"'
    )


def test_shared_asset_cdn_url_encodes_spaces_and_preserves_slashes() -> None:
    """HF CDN URLs pin the dataset revision and URL-encode tricky filenames."""
    url = blind.shared_asset_cdn_url("sf-city/my file.glb", "user/ds", "abc123")
    assert url == "https://huggingface.co/datasets/user/ds/resolve/abc123/sf-city/my%20file.glb"


def test_vote_store_enforces_play_gate_rate_limits_and_deblinds(tmp_path: Path) -> None:
    """Heartbeat anti-spoof, play gate, server-side de-blinding, and dedup all hold."""
    store = storage.VoteStore(
        data_dir=tmp_path / "data",
        build_to_contender={"b-alpha": "kimi", "b-beta": "opus"},
        race_id="test-race",
    )
    # Assign opus to slot A and kimi to slot B to verify slot -> contender translation.
    state = store.ensure_session("session-1234567890", "b-beta", "b-alpha", now=980.0)
    assert state.play_a_s == 0.0
    assert not state.voted

    # Burst spam 0.1 s apart cannot credit more than elapsed time + 1.5 s grace.
    s1 = store.record_heartbeat("session-1234567890", "a", 99.0, now=1000.0)
    assert s1.play_a_s == storage.MAX_HEARTBEAT_STEP_S
    s2 = store.record_heartbeat("session-1234567890", "a", 10.0, now=1000.1)
    assert s2.play_a_s == pytest.approx(storage.MAX_HEARTBEAT_STEP_S + 1.6, abs=0.05)

    # Voting before both slots hit min_play_seconds=15 must be rejected.
    picks = {q: "a" for q in storage.QUESTIONS}
    with pytest.raises(ValueError, match="play at least"):
        store.submit_vote("session-1234567890", picks, min_play_seconds=15.0)

    # Accumulate legitimate wall-clock play time on both slots.
    store.record_heartbeat("session-1234567890", "a", 10.0, now=1015.0)
    store.record_heartbeat("session-1234567890", "b", 10.0, now=1025.0)
    store.record_heartbeat("session-1234567890", "b", 10.0, now=1036.0)

    summary = store.submit_vote(
        "session-1234567890",
        {
            "plays_better": "a",
            "looks_better": "b",
            "better_main_character": "tie",
            "overall": "a",
        },
        min_play_seconds=15.0,
    )
    assert summary["a_contender"] == "opus"
    assert summary["b_contender"] == "kimi"
    assert summary["contender_picks"] == {
        "plays_better": "opus",
        "looks_better": "kimi",
        "better_main_character": "tie",
        "overall": "opus",
    }

    # Second vote from the same session is rejected.
    with pytest.raises(ValueError, match="already voted"):
        store.submit_vote("session-1234567890", picks, min_play_seconds=15.0)

    # Tallies and JSONL mirror match the submitted ballot.
    tallies = store.tallies()
    assert tallies["total_ballots"] == 1
    assert tallies["questions"]["plays_better"]["counts"] == {"kimi": 0, "opus": 1, "tie": 0}
    assert tallies["questions"]["looks_better"]["counts"] == {"kimi": 1, "opus": 0, "tie": 0}
    jsonl_rows = [
        json.loads(line) for line in store.jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(jsonl_rows) == 1
    assert jsonl_rows[0]["race_id"] == "test-race"


def test_prepare_packages_opaque_builds_strips_shared_assets_and_scans_leaks(
    tmp_path: Path,
) -> None:
    """`package_race` strips `assets/gt-gpu/`, scrubs HTML `<title>`, and flags JS leaks."""
    race_dir = tmp_path / "v15-test"
    for contender, js_body in (
        ("kimi", "console.log('clean game');"),
        ("opus", "console.log('built by claude');"),
    ):
        dist = race_dir / contender / "workspace" / "dist"
        (dist / "assets" / "gt-gpu" / "sf-city").mkdir(parents=True)
        (dist / "assets" / "gt-gpu" / "sf-city" / "huge.glb").write_bytes(b"0" * 1024)
        (dist / "assets" / "index.js").write_text(js_body, encoding="utf-8")
        (dist / "index.html").write_text(
            f"<html><head><title>GTA by {contender}</title></head><body></body></html>",
            encoding="utf-8",
        )

    out_dir = tmp_path / "builds"
    manifest, leaks = prepare.package_race(race_dir, out_dir, link_local_assets=True)

    builds = manifest["builds"]
    assert isinstance(builds, dict)
    assert len(builds) == 2
    assert (out_dir / "_shared_assets" / "sf-city" / "huge.glb").exists()

    for bid in builds:
        assert "kimi" not in bid and "opus" not in bid
        assert not (out_dir / bid / "assets" / "gt-gpu").exists()
        assert "<title>Grand Theft GPU</title>" in (out_dir / bid / "index.html").read_text()

    # The JS leak in opus's bundle must be reported while the scrubbed title is clean.
    assert len(leaks) == 1
    assert leaks[0].contender == "opus"
    assert leaks[0].match.lower() == "claude"


SID = "session-1234567890"
BUILDS = {"b-alpha": "kimi", "b-beta": "opus"}
ALL_A = {q: "a" for q in storage.QUESTIONS}


def _played_store(tmp_path: Path, **kwargs: object) -> storage.VoteStore:
    """Returns a store with session `SID` that has 30 s verified in each slot."""
    store = storage.VoteStore(tmp_path / "data", BUILDS, race_id="race-2", **kwargs)
    store.ensure_session(SID, "b-alpha", "b-beta", now=1000.0)
    store.record_heartbeat(SID, "a", 15.0, now=1015.0)
    store.record_heartbeat(SID, "a", 15.0, now=1030.0)
    store.record_heartbeat(SID, "b", 15.0, now=1045.0)
    store.record_heartbeat(SID, "b", 15.0, now=1060.0)
    return store


def test_heartbeats_share_one_clock_across_slots(tmp_path: Path) -> None:
    """Pinging A and B in parallel can't accrue play time faster than real time."""
    store = storage.VoteStore(tmp_path / "data", BUILDS)
    store.ensure_session(SID, "b-alpha", "b-beta", now=1000.0)
    store.record_heartbeat(SID, "a", 15.0, now=1015.0)
    state = store.record_heartbeat(SID, "b", 15.0, now=1015.0)
    # B's ping comes 0 s after A's, so it earns only the jitter grace.
    assert state.play_a_s == 15.0
    assert state.play_b_s == pytest.approx(storage.HEARTBEAT_GRACE_S)
    # A first ping can't claim more than the time since the session was created.
    store.ensure_session("session-fresh-000000", "b-alpha", "b-beta", now=2000.0)
    fresh = store.record_heartbeat("session-fresh-000000", "a", 15.0, now=2002.0)
    assert fresh.play_a_s == pytest.approx(2.0 + storage.HEARTBEAT_GRACE_S)


def test_tallies_count_only_the_current_race(tmp_path: Path) -> None:
    """Ballots from another race in the same vote dataset never reach this race's tally."""
    store = _played_store(tmp_path)
    store.submit_vote(SID, ALL_A, min_play_seconds=30.0)
    with store._db() as conn:
        conn.execute(
            storage._INSERT_VOTE_SQL,
            (
                "old-sid-000000000000",
                "race-1",
                "x",
                "y",
                "opus",
                "kimi",
                "{}",
                json.dumps({q: "opus" for q in storage.QUESTIONS}),
                60.0,
                60.0,
                1.0,
                "",
            ),
        )
    tallies = store.tallies()
    assert tallies["total_ballots"] == 1
    assert tallies["questions"]["overall"]["counts"] == {"kimi": 1, "opus": 0, "tie": 0}


def test_ip_caps_block_new_sessions_and_extra_votes(tmp_path: Path) -> None:
    """One IP hits 429-style errors past its session and ballot caps."""
    store = storage.VoteStore(tmp_path / "data", BUILDS)
    store.ensure_session(
        "sid-one-0000000000", "b-alpha", "b-beta", ip_hash="ip1", max_sessions_per_ip=1, now=1000.0
    )
    # Re-resolving an existing session never counts against the cap.
    store.ensure_session(
        "sid-one-0000000000", "b-alpha", "b-beta", ip_hash="ip1", max_sessions_per_ip=1, now=1001.0
    )
    with pytest.raises(storage.RateLimitedError):
        store.ensure_session(
            "sid-two-0000000000",
            "b-alpha",
            "b-beta",
            ip_hash="ip1",
            max_sessions_per_ip=1,
            now=1002.0,
        )
    # A different IP is unaffected.
    store.ensure_session(
        "sid-three-00000000", "b-alpha", "b-beta", ip_hash="ip2", max_sessions_per_ip=1, now=1002.0
    )

    voter = _played_store(tmp_path / "v")
    voter.ensure_session("sid-second-0000000", "b-alpha", "b-beta", now=1000.0)
    voter.record_heartbeat("sid-second-0000000", "a", 20.0, now=1070.0)
    voter.record_heartbeat("sid-second-0000000", "b", 20.0, now=1090.0)
    voter.submit_vote(SID, ALL_A, 15.0, ip_hash="ip1", max_votes_per_ip=1)
    with pytest.raises(storage.RateLimitedError):
        voter.submit_vote("sid-second-0000000", ALL_A, 15.0, ip_hash="ip1", max_votes_per_ip=1)


def test_failed_restore_never_starts_vote_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error while restoring votes disables the push that would erase history."""
    import huggingface_hub

    def _boom(**_: object) -> str:
        raise ConnectionError("hub unreachable")

    started: list[str] = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _boom)
    monkeypatch.setattr(
        storage.VoteStore, "_start_hf_sync", lambda self, repo, token: started.append(repo)
    )
    storage.VoteStore(tmp_path / "data", BUILDS, dataset_repo="ns/votes")
    assert started == []


def test_restore_merges_remote_and_local_votes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a restore, votes.jsonl holds remote history plus votes already in local SQLite."""
    import huggingface_hub

    local = _played_store(tmp_path)
    local.submit_vote(SID, ALL_A, min_play_seconds=30.0)
    remote = tmp_path / "remote.jsonl"
    remote.write_text(
        json.dumps(
            {
                "sid": "remote-sid-00000000",
                "race_id": "race-1",
                "a_build": "x",
                "b_build": "y",
                "a_contender": "kimi",
                "b_contender": "opus",
                "slot_picks": {},
                "contender_picks": {},
                "play_a_s": 60,
                "play_b_s": 60,
                "submitted_at": 5,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    started: list[str] = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda **_: str(remote))
    monkeypatch.setattr(
        storage.VoteStore, "_start_hf_sync", lambda self, repo, token: started.append(repo)
    )
    restored = storage.VoteStore(
        tmp_path / "data", BUILDS, race_id="race-2", dataset_repo="ns/votes"
    )
    sids = {
        json.loads(line)["sid"]
        for line in restored.jsonl_path.read_text(encoding="utf-8").splitlines()
    }
    assert sids == {SID, "remote-sid-00000000"}
    assert started == ["ns/votes"]


def test_record_events_mirrors_deblinded_batches_and_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Event batches land in SQLite and JSONL with build, contender and play time."""
    store = _played_store(tmp_path)
    events = [[12.0, "kd", "KeyW"], [400.0, "ku", "KeyW"], [500.0, "md", "0"]]
    assert store.record_events(SID, "b", events, now=1061.0) == 3

    (line,) = store.events_path.read_text(encoding="utf-8").splitlines()
    rec = json.loads(line)
    assert rec["build"] == "b-beta"
    assert rec["contender"] == "opus"
    assert rec["play_s"] == 30.0
    assert rec["events"] == events

    monkeypatch.setattr(storage, "MAX_EVENTS_PER_SESSION", 4)
    assert store.record_events(SID, "a", events) == 1
    assert store.record_events(SID, "a", events) == 0
    with pytest.raises(KeyError):
        store.record_events("unknown-sid-00000000", "a", events)


def test_injected_html_includes_identical_input_logger() -> None:
    """Both slots get the same logger, bound to their slot and token."""
    html = "<html><head></head><body></body></html>"
    out_a = blind.inject_slot_shim(html, "a", token="tok.sig")
    out_b = blind.inject_slot_shim(html, "b", token="tok.sig")
    assert 'var T="tok.sig",L="a"' in out_a
    assert '"/api/events"' in out_a
    assert out_a.replace('L="a"', "").replace("/play/a/", "") == out_b.replace('L="b"', "").replace(
        "/play/b/", ""
    )


@pytest.fixture
def arena_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Imports `arena/app.py` against a temp manifest and returns a FastAPI test client."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import importlib

    from fastapi.testclient import TestClient

    builds = tmp_path / "builds"
    for bid in BUILDS:
        (builds / bid / "assets").mkdir(parents=True)
        (builds / bid / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
        (builds / bid / "assets" / "car.glb").write_text(bid, encoding="utf-8")
    manifest = {
        "race_id": "race-2",
        "hf_assets_repo": "ns/assets",
        "hf_assets_revision": "abc",
        "builds": {bid: {"contender": c, "label": c} for bid, c in BUILDS.items()},
    }
    (builds / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setenv("ARENA_BUILDS_DIR", str(builds))
    monkeypatch.setenv("ARENA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ARENA_SECRET", "test-secret")
    monkeypatch.delenv("ARENA_MANIFEST_JSON", raising=False)
    monkeypatch.delenv("VOTE_DATASET_REPO", raising=False)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")
    return TestClient(app_module.app), app_module


def test_root_asset_fallback_redirects_to_slot_url(arena_client) -> None:  # noqa: ANN001
    """`/assets/x` redirects to the slot's tokenized URL instead of serving a shared body."""
    client, _ = arena_client
    token = client.get("/api/session").json()["token"]
    resp = client.get(
        "/assets/car.glb",
        headers={"referer": f"http://testserver/s/{token}/play/b/"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    assert resp.headers["location"] == f"/s/{token}/play/b/assets/car.glb"
    payload = blind.verify_session(token, "test-secret", set(BUILDS))
    assert payload is not None
    followed = client.get(resp.headers["location"])
    assert followed.text == payload["order"][1]


def test_events_endpoint_requires_a_session(arena_client) -> None:  # noqa: ANN001
    """Batches with a valid token are stored; batches without a session are rejected."""
    client, app_module = arena_client
    token = client.get("/api/session").json()["token"]
    batch = {"slot": "a", "events": [[1.0, "kd", "KeyW"], [2.0, "ku", "KeyW"]]}
    stored = client.post("/api/events", json={**batch, "token": token})
    assert stored.status_code == 200
    assert stored.json() == {"stored": 2}

    client.cookies.clear()
    assert client.post("/api/events", json=batch).status_code == 401
    bad = {**batch, "token": token, "events": [[1.0, "keylogger", "x"]]}
    assert client.post("/api/events", json=bad).status_code == 422
    assert app_module.runtime.store is not None


def test_leak_pattern_catches_camel_case_but_not_substrings() -> None:
    """Minified identifiers leak; codec tags and longer words don't."""
    for leak in ("claudeMode", "useOpus", "KIMI_KEY", "by Anthropic.", "fireworks"):
        assert prepare.LEAK_PATTERN.search(leak), leak
    for clean in ("libopus", "Claudette", "opuscule", "akimbo"):
        assert not prepare.LEAK_PATTERN.search(clean), clean


def test_secret_file_is_shared_and_never_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arena_client
) -> None:  # noqa: ANN001
    """Two workers loading the secret without ARENA_SECRET get the same non-empty key."""
    _, app_module = arena_client
    tmp_path = tmp_path / "secret"
    tmp_path.mkdir()
    monkeypatch.delenv("ARENA_SECRET")
    first = app_module._load_session_secret(tmp_path)
    second = app_module._load_session_secret(tmp_path)
    assert first and first == second
    assert [p.name for p in tmp_path.iterdir()] == [".session_secret"]


def test_offline_restore_never_starts_vote_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No connection and no cache (LocalEntryNotFoundError) is a failed restore, not 'no votes'."""
    import huggingface_hub
    from huggingface_hub.errors import LocalEntryNotFoundError

    def _offline(**_: object) -> str:
        raise LocalEntryNotFoundError("offline and not cached")

    started: list[str] = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", _offline)
    monkeypatch.setattr(
        storage.VoteStore, "_start_hf_sync", lambda self, repo, token: started.append(repo)
    )
    storage.VoteStore(tmp_path / "data", BUILDS, dataset_repo="ns/votes")
    assert started == []


def test_events_endpoint_bounds_code_and_body_size(arena_client) -> None:  # noqa: ANN001
    """Long event codes are rejected and oversized bodies never get parsed."""
    client, app_module = arena_client
    token = client.get("/api/session").json()["token"]
    long_code = {"token": token, "slot": "a", "events": [[1.0, "kd", "K" * 33]]}
    assert client.post("/api/events", json=long_code).status_code == 422
    huge = json.dumps({"token": token, "slot": "a", "events": [], "pad": "x" * 300_000})
    resp = client.post("/api/events", content=huge, headers={"content-type": "application/json"})
    assert resp.status_code == 413
    assert app_module.MAX_API_BODY_BYTES < len(huge)


def test_bundle_names_lose_their_hashes(tmp_path: Path) -> None:
    """Hashed Vite bundle names are renamed and every reference follows."""
    build = tmp_path / "b-x"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(
        '<script src="/assets/index-CEyXDvVM.js"></script><link href="/assets/index-BHOQRlWH.css">',
        encoding="utf-8",
    )
    (build / "assets" / "index-CEyXDvVM.js").write_text(
        'import("./chunk-Ab_9xY-z.js")', encoding="utf-8"
    )
    (build / "assets" / "chunk-Ab_9xY-z.js").write_text("x", encoding="utf-8")
    (build / "assets" / "index-BHOQRlWH.css").write_text("a{}", encoding="utf-8")
    (build / "assets" / "Player_Idle.fbx").write_bytes(b"bin")

    renames = prepare.neutralize_bundle_names(build)
    assert renames == {
        "chunk-Ab_9xY-z.js": "chunk.js",
        "index-BHOQRlWH.css": "index.css",
        "index-CEyXDvVM.js": "index.js",
    }
    names = sorted(p.name for p in (build / "assets").iterdir())
    assert names == ["Player_Idle.fbx", "chunk.js", "index.css", "index.js"]
    html = (build / "index.html").read_text(encoding="utf-8")
    assert "/assets/index.js" in html and "/assets/index.css" in html
    assert (build / "assets" / "index.js").read_text(encoding="utf-8") == 'import("./chunk.js")'
