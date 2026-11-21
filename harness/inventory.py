"""Query layer behind `buildoff inventory`: search the asset catalog, emit JSON.

Designed for agents:
- non-interactive: every input is a flag or argument; nothing prompts
- deterministic: same catalog + same arguments = byte-identical output
  (stable sort orders, no timestamps, sorted keys)
- self-documenting: `buildoff inventory schema` describes every field and
  command, and every command's `--help` works
- structured: results go to stdout as JSON (default) or JSON Lines; errors go
  to stderr as `{"error": ..., "hint": ...}` with a non-zero exit code

Reads only `assets/catalog.json` (built by `harness.catalog`) with the standard
library, so queries are instant and need no 3D libraries.
"""

import difflib
import json
import sys
from pathlib import Path
from typing import Any

from harness.catalog import CATALOG_PATH, tokens

# Score weights for `search`: a query word matching the id outranks one that
# only appears in a tag, which outranks a substring hit.
WEIGHT_ID: int = 5
WEIGHT_NAME: int = 4
WEIGHT_TAG: int = 3
WEIGHT_SUBSTRING: int = 1
# Bonus scaled by the share of the asset id's words the query covers, so a
# query matching all of "cars/police" outranks one matching 2 of 3 words of
# "cars/tractor-police".
WEIGHT_COVERAGE: int = 4

# Fields included in list/search output unless --full is passed; full records
# (parts, joints) can be large, and `show` gives the complete record anyway.
SUMMARY_FIELDS: tuple[str, ...] = (
    "id",
    "category",
    "kind",
    "name",
    "url",
    "triangles",
    "size_m",
    "license",
)

SCHEMA: dict[str, Any] = {
    "description": (
        "Inventory of 3D assets available to the game. Each asset is a .glb "
        "loadable with three.js GLTFLoader from its `url` inside a race workspace."
    ),
    "fields": {
        "id": "Stable unique id, '<folder>/<file stem>'. Use with `show`.",
        "category": "Broad group: loot, vehicle, prop (more as packs are added).",
        "kind": "Finer type, e.g. vehicle vs vehicle-part for car-kit pieces.",
        "name": "Human-readable name.",
        "url": "Path the game fetches, e.g. /assets/gt-gpu/cars/taxi.glb.",
        "repo_path": "Path of the file in this repository.",
        "format": "File format (glb).",
        "bytes": "File size in bytes.",
        "triangles": "Rendered triangle count (sum over all mesh instances).",
        "size_m": "Bounding box in metres, glTF axes: y is up.",
        "parts": "Named sub-objects you can move independently (wheels, doors, rotors).",
        "joints": (
            "Articulations (props only): name, type revolute|prismatic, parent_link, "
            "child_link, axis (USD Z-up letter; USD Z = glTF Y, USD Y = glTF -Z), "
            "lower/upper limits (degrees for revolute, metres for prismatic; null = no limit)."
        ),
        "tags": "Lowercase search keywords, including synonyms (cop, robotaxi, vault).",
        "group": "Source dataset's own grouping, when it has one (USDCraft props).",
        "source": "Where the asset came from.",
        "source_url": "Link to the original.",
        "license": "SPDX license id.",
    },
    "commands": {
        "categories": "Count of assets per category and kind.",
        "list": "All assets (summary fields), filterable by --category/--kind/--tag.",
        "search": "Rank assets against query words; ties break by id.",
        "show": "Full record for one or more ids.",
        "schema": "This document.",
    },
    "output": (
        "JSON on stdout (--format jsonl for one record per line). Errors: JSON on "
        "stderr, exit 1 (not found) or 2 (bad input)."
    ),
}


class InventoryError(Exception):
    """A user-facing error with a hint; rendered as JSON on stderr."""

    def __init__(self, message: str, hint: str, code: int = 1) -> None:
        """Stores the message, a hint for fixing it, and the exit code."""
        super().__init__(message)
        self.hint = hint
        self.code = code


def load(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    """Loads the catalog's asset records.

    Raises:
        InventoryError: if the catalog hasn't been built
    """
    if not path.exists():
        raise InventoryError(f"catalog not found at {path}", "run: uv run buildoff assets catalog")
    return json.loads(path.read_text())["assets"]


def summarize(asset: dict[str, Any], full: bool) -> dict[str, Any]:
    """Returns the record trimmed to SUMMARY_FIELDS unless full is True.

    A search "score" is always kept, so ranked output shows why each hit ranked.
    """
    if full:
        return asset
    return {k: asset[k] for k in (*SUMMARY_FIELDS, "score") if k in asset}


def filter_assets(
    assets: list[dict[str, Any]], category: str | None, kind: str | None, tag: str | None
) -> list[dict[str, Any]]:
    """Keeps assets matching every given filter (exact, case-insensitive)."""
    out = assets
    if category:
        out = [a for a in out if a["category"] == category.lower()]
    if kind:
        out = [a for a in out if a["kind"] == kind.lower()]
    if tag:
        out = [a for a in out if tag.lower() in a["tags"]]
    return out


def stem(word: str) -> str:
    """Folds simple plurals so "car" matches "cars" and "safes" matches "safe"."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def score(asset: dict[str, Any], words: list[str]) -> float:
    """Scores one asset against query words; 0 means no word matched.

    Every query word must match something, so "police car" doesn't return
    every car. Within that, id and name hits outrank tag and substring hits.
    """
    id_tokens = {stem(t) for t in tokens(asset["id"])}
    name_tokens = {stem(t) for t in tokens(asset["name"])}
    tags = {stem(t) for t in asset["tags"]}
    haystack = " ".join([asset["id"], asset["name"], *asset["tags"]]).lower()
    total = 0.0
    words = [stem(w) for w in words]
    for w in words:
        hit = (
            WEIGHT_ID * (w in id_tokens)
            + WEIGHT_NAME * (w in name_tokens)
            + WEIGHT_TAG * (w in tags)
            + WEIGHT_SUBSTRING * (w in haystack)
        )
        if hit == 0:
            return 0
        total += hit
    covered = len(id_tokens & set(words)) / len(id_tokens) if id_tokens else 0.0
    return round(total + WEIGHT_COVERAGE * covered, 3)


def search(assets: list[dict[str, Any]], query: list[str]) -> list[dict[str, Any]]:
    """Returns assets matching all query words, best first, ties by id.

    Each result gains a "score" field so callers can see why it ranked.
    """
    words = [t for q in query for t in tokens(q)]
    if not words:
        raise InventoryError("empty query", "pass one or more words, e.g. `search police car`", 2)
    scored = [(score(a, words), a) for a in assets]
    hits = [(s, a) for s, a in scored if s > 0]
    hits.sort(key=lambda sa: (-sa[0], sa[1]["id"]))
    return [{**a, "score": s} for s, a in hits]


def categories(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Counts assets per (category, kind), sorted by category then kind."""
    counts: dict[tuple[str, str], int] = {}
    for a in assets:
        key = (a["category"], a["kind"])
        counts[key] = counts.get(key, 0) + 1
    return [{"category": c, "kind": k, "count": n} for (c, k), n in sorted(counts.items())]


def show(assets: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    """Returns full records for the given ids, in the order asked.

    Raises:
        InventoryError: listing every unknown id and the closest matches
    """
    by_id = {a["id"]: a for a in assets}
    missing = [i for i in ids if i not in by_id]
    if missing:
        # difflib is deterministic: same ids in, same suggestions out.
        ids_all = [a["id"] for a in assets]
        near = sorted({c for m in missing for c in difflib.get_close_matches(m, ids_all, n=3)})
        raise InventoryError(
            f"unknown id(s): {', '.join(missing)}",
            f"did you mean: {', '.join(near)}" if near else "list ids with `inventory list`",
        )
    return [by_id[i] for i in ids]


def emit(data: Any, fmt: str) -> None:
    """Writes results to stdout as pretty JSON or JSON Lines (one record per line)."""
    if fmt == "jsonl" and isinstance(data, list):
        for row in data:
            sys.stdout.write(json.dumps(row, sort_keys=True) + "\n")
    else:
        sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")


def fail(err: InventoryError) -> int:
    """Writes an error as JSON to stderr and returns its exit code."""
    sys.stderr.write(json.dumps({"error": str(err), "hint": err.hint}) + "\n")
    return err.code
