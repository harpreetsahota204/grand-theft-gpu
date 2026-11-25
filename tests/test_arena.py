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
if str(ARENA_DIR) not in sys.path:
    sys.path.insert(0, str(ARENA_DIR))

import blind  # noqa: E402
import prepare  # noqa: E402
import storage  # noqa: E402


def test_session_cookie_round_trip_and_tamper_rejection() -> None:
    """Valid tokens decode cleanly; tampered or mismatched-build tokens are rejected."""
    build_ids = ("b-1111aaaa", "b-2222bbbb")
    secret = "test-secret-key"
    payload = blind.new_session(build_ids)

    assert set(payload["order"]) == set(build_ids)
    token = blind.sign_session(payload, secret)
    decoded = blind.verify_session(token, secret, set(build_ids))
    assert decoded == payload

    # Wrong secret, modified signature, or stale build IDs must all fail closed.
    assert blind.verify_session(token, "wrong-secret", set(build_ids)) is None
    assert blind.verify_session(token[:-1] + "X", secret, set(build_ids)) is None
    assert blind.verify_session(token, secret, {"b-other1", "b-other2"}) is None
    assert blind.verify_session(None, secret, set(build_ids)) is None


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
    state = store.ensure_session("session-1234567890", "b-beta", "b-alpha")
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
