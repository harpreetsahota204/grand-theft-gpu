"""Downloads the curated third-party asset sets listed in `scripts/mirror_sources.json`.

These are Hugging Face datasets (mostly codepawl's web-ready glTF conversions of
Microsoft Rocketbox and Kenney) that we mirror into our own asset dataset. Each
source is pinned to an exact revision, so a mirror built today and one built
next year contain the same bytes.

Per source, only folders whose name matches the source's include/exclude rules
are kept (for example: people only, no animals or children), across the listed
tiers (`objects/`, `lods/`, ...), plus its top-level license and README files.

Called by `buildoff assets mirror` (see `harness.cli`).
"""

import json
from pathlib import Path
from typing import TypedDict

from huggingface_hub import HfApi, snapshot_download

from harness.config import REPO_ROOT

PLAN_PATH: Path = REPO_ROOT / "scripts" / "mirror_sources.json"


class MirrorSource(TypedDict):
    """One entry of mirror_sources.json; see that file for field meanings."""

    id: str
    repo: str
    revision: str
    tiers: list[str]
    include_prefixes: list[str]
    exclude_substrings: list[str]
    exclude_items: list[str]
    top_level: list[str]
    license: str
    creator: str
    creator_url: str
    converted_by: str
    what: str


def load_plan() -> list[MirrorSource]:
    """Reads the mirror plan from scripts/mirror_sources.json."""
    return json.loads(PLAN_PATH.read_text())["sources"]


def selected_files(src: MirrorSource) -> list[str]:
    """Lists the repo files to mirror for one source, at its pinned revision.

    A file is kept if it's a listed top-level file, or if it sits in a listed
    tier and its item folder (`<tier>/<item>/...`) matches an include prefix,
    contains no exclude substring, and isn't listed in `exclude_items`.

    Returns:
        sorted repo-relative paths
    """
    files = HfApi().list_repo_files(src["repo"], repo_type="dataset", revision=src["revision"])
    keep = set(src["top_level"]) & set(files)
    for path in files:
        parts = path.split("/")
        if len(parts) < 3 or parts[0] not in src["tiers"]:
            continue
        item = parts[1]
        excluded = item in src.get("exclude_items", []) or any(
            s in item for s in src["exclude_substrings"]
        )
        if any(item.startswith(p) for p in src["include_prefixes"]) and not excluded:
            keep.add(path)
    return sorted(keep)


def mirror(out: Path, only: str | None = None) -> dict[str, int]:
    """Downloads every planned source (or just one) into `out/<source id>/`.

    Args:
        out: staging root for the mirror
        only: a source id to restrict to, or None for all

    Returns:
        files downloaded per source id
    """
    counts: dict[str, int] = {}
    for src in load_plan():
        if only and src["id"] != only:
            continue
        files = selected_files(src)
        snapshot_download(
            repo_id=src["repo"],
            repo_type="dataset",
            revision=src["revision"],
            allow_patterns=files,
            local_dir=out / src["id"],
        )
        counts[src["id"]] = len(files)
        print(f"{src['id']}: {len(files)} files from {src['repo']}@{src['revision'][:7]}")
    return counts
