"""The asset catalog as races use it: id lookup for `buildoff fetch` and the models' search tool."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harness import fetch
from harness.config import CATALOG_PATH
from harness.seed import TOOL_PATH


def test_ids_map_to_dataset_paths() -> None:
    """A catalog id becomes its dataset path; unknown ids are named in the error."""
    asset = json.loads(CATALOG_PATH.read_text())["assets"][0]
    assert asset["hf_path"] in fetch.patterns_for_ids([asset["id"]])
    with pytest.raises(KeyError, match="no-such-asset"):
        fetch.patterns_for_ids(["no-such-asset"])


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_models_search_tool_finds_a_police_car(tmp_path: Path) -> None:
    """tools/assets.mjs, as seeded into a workspace, ranks a police vehicle first for "cop car"."""
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copy2(TOOL_PATH, tools / "assets.mjs")
    shutil.copy2(CATALOG_PATH, tools / "catalog.json")
    node = subprocess.run(
        ["node", str(tools / "assets.mjs"), "search", "cop", "car", "--limit", "3"],
        capture_output=True,
        text=True,
        check=True,
    )
    rows = json.loads(node.stdout)
    assert rows and "police" in rows[0]["id"]
