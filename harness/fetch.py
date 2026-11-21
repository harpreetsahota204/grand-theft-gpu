"""Downloads assets from the Hugging Face dataset at the pinned revision.

Two uses:
- `core()`: the seeded set every race workspace starts with (the full web tier,
  ~508 MB: people, motions, Kenney, SF city, props, GPU, Quaternius clips, plus
  each folder's license and attribution files). `harness.seed` copies it into
  each workspace under `public/assets/gt-gpu/`.
- `fetch()`: anything else on demand, by catalog id or dataset path pattern
  (`buildoff assets fetch`).

Downloads go through huggingface_hub's cache, so repeated races and fetches
don't re-download; pinning `HF_ASSETS_REVISION` makes every race identical.
"""

import json
from pathlib import Path

from huggingface_hub import snapshot_download

from harness.catalog import CATALOG_PATH
from harness.config import HF_ASSETS_REPO, HF_ASSETS_REVISION

# Licence and attribution files travel with the assets into every workspace.
STEWARDSHIP: tuple[str, ...] = ("LICENSE*", "LICENSES.md", "ATTRIBUTION.md", "NOTICE.md")

# The seeded set: the full web tier. Optional extras (people's lods/mobile/
# collision tiers, MHR bodies, the raw OSM cache) are left for on-demand fetch.
CORE_PATTERNS: list[str] = [
    "README.md",
    "gpu/*",
    "usdcraft-props/*",
    "quaternius-animations/*",
    "sf-city/*.glb",
    "sf-city/*.json",
    "kenney/objects/*",
    "rocketbox-avatars/objects/*",
    "rocketbox-motions/objects/*",
    "vehicles-objaverse/objects/*",
    "vehicles-quaternius/objects/*",
    *[f"{folder}/{f}" for folder in ("kenney", "rocketbox-avatars", "rocketbox-motions", "sf-city",
                   "vehicles-objaverse", "vehicles-quaternius")
      for f in STEWARDSHIP],
]  # fmt: skip


def download(patterns: list[str], out: Path | None = None) -> Path:
    """Downloads dataset files matching any pattern, at the pinned revision.

    Args:
        patterns: dataset-relative glob patterns (fnmatch; `*` crosses `/`)
        out: folder to place files in, mirroring the dataset layout; None keeps
            them in the huggingface_hub cache

    Returns:
        the folder holding the files (dataset layout)
    """
    path = snapshot_download(
        repo_id=HF_ASSETS_REPO,
        repo_type="dataset",
        revision=HF_ASSETS_REVISION,
        allow_patterns=patterns,
        local_dir=out,
    )
    return Path(path)


def core(out: Path | None = None) -> Path:
    """Downloads the seeded core set; returns its folder (dataset layout)."""
    return download(CORE_PATTERNS, out)


def patterns_for_ids(ids: list[str], with_tiers: bool = False) -> list[str]:
    """Maps catalog ids to dataset path patterns.

    Args:
        ids: catalog ids, e.g. "rocketbox-avatars/business-female-01"
        with_tiers: also include people's optional tiers (lods, mobile, collision)

    Raises:
        KeyError: listing ids that aren't in the catalog
    """
    assets = {a["id"]: a for a in json.loads(CATALOG_PATH.read_text())["assets"]}
    missing = [i for i in ids if i not in assets]
    if missing:
        raise KeyError(f"unknown id(s): {', '.join(missing)}")
    paths: list[str] = []
    for i in ids:
        a = assets[i]
        paths.append(a["hf_path"])
        if with_tiers:
            paths += list(a.get("optional_tiers", {}).values())
    return sorted(set(paths))
