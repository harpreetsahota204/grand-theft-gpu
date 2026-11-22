"""Asset pipeline safety (zip-slip, pinned hashes) and search parity with the models' tool."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import inventory
from harness.assets import safe_join, verify
from harness.catalog import CATALOG_PATH
from harness.seed import TOOL_PATH


@pytest.mark.parametrize("name", ["../x", "a/../../x", "/etc/passwd", "a/../../../.zshrc"])
def test_safe_join_refuses_escapes(tmp_path: Path, name: str) -> None:
    """Archive members can't write outside the staging folder."""
    with pytest.raises(ValueError):
        safe_join(tmp_path, name)


def test_safe_join_allows_nested_members(tmp_path: Path) -> None:
    """Ordinary member paths, including harmless '..' inside the root, resolve normally."""
    assert safe_join(tmp_path, "a/b/../c.ogg") == (tmp_path / "a" / "c.ogg").resolve()


def test_verify_rejects_changed_upstream() -> None:
    """A download whose hash doesn't match the pin fails loudly."""
    sha_of_abc = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert verify(b"abc", sha_of_abc, "x") == b"abc"
    with pytest.raises(ValueError):
        verify(b"abd", sha_of_abc, "x")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
@pytest.mark.parametrize(
    "argv",
    [
        ["search", "police", "car", "--limit", "10"],
        ["search", "walk", "--limit", "10"],
        ["list", "--category", "VEHICLE", "--limit", "10"],
        ["list", "--tag", "Heist-Target"],
    ],
)
def test_models_tool_matches_python_inventory(tmp_path: Path, argv: list[str]) -> None:
    """tools/assets.mjs (what the models run) returns the same ids as `buildoff inventory`."""
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copy2(TOOL_PATH, tools / "assets.mjs")
    shutil.copy2(CATALOG_PATH, tools / "catalog.json")
    node = subprocess.run(
        ["node", str(tools / "assets.mjs"), *argv], capture_output=True, text=True, check=True
    )
    js_ids = [row["id"] for row in json.loads(node.stdout)]

    assets = inventory.load()
    opts = dict(zip(argv[1::2], argv[2::2], strict=False)) if argv[0] == "list" else {}
    pool = inventory.filter_assets(
        assets, opts.get("--category"), opts.get("--kind"), opts.get("--tag")
    )
    words = [w for w in argv[1:] if not w.startswith("--") and not w.isdigit()]
    rows = inventory.search(pool, words) if argv[0] == "search" else pool
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None
    py_ids = [r["id"] for r in rows[:limit]]
    assert js_ids == py_ids
    assert js_ids, "query should match something"
