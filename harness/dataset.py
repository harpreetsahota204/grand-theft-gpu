"""Assembles the Hugging Face asset dataset folder (harpreetsahota/grand-theft-gpu-assets).

Run after `buildoff assets mirror` and `buildoff assets city`. It finishes the
staging folder (`config.MIRROR_DIR`) so every subfolder is self-describing:

- mirrored sources (from scripts/mirror_sources.json): filters the upstream
  `metadata.jsonl` to the items we kept, and writes `ATTRIBUTION.md` with the
  creator, converter, pinned revision, what was kept, and what we changed
- our own assets from this repo's assets/ (the GPU and the converted USDCraft
  props) are copied in with their licence files
- the hand-written cards in this repo's `dataset_card/` (the top-level
  `README.md` and per-folder files for the sets we built ourselves) are
  copied in last

`build` never uploads. `publish` uploads the finished folder, and is only run
after a human has reviewed the cards.
Called by `buildoff assets dataset` (see `harness.cli`).
"""

import json
import shutil
from pathlib import Path

from huggingface_hub import HfApi

from harness.config import ASSETS_DIR, MIRROR_DIR, REPO_ROOT
from harness.mirror import MirrorSource, load_plan

HF_REPO: str = "harpreetsahota/grand-theft-gpu-assets"

# Our own assets that live in this repo and go into the dataset as-is.
OWN_SETS: dict[str, dict[str, str]] = {
    "gpu": {
        "from": "gpu",
        "license": "CC0-1.0",
        "creator": "Grab3D (https://grab3d.com/models/electronics/graphics-card/)",
        "what": "The loot: a stylised graphics card with separately animatable fans and RGB strips",
        "changes": "None. Files as downloaded (light tier GLB, licence, manifest).",
    },
    "usdcraft-props": {
        "from": "props",
        "license": "Apache-2.0",
        "creator": "NVIDIA (USDCraft-10K, https://huggingface.co/datasets/nvidia/USDCraft-10K)",
        "what": "45 props (server racks, safes, an ATM, a forklift, a drone, street furniture)",
        "changes": (
            "Converted from OpenUSD to GLB with scripts/convert_usdcraft.py in "
            "https://github.com/harpreetsahota204/grand-theft-gpu: collision meshes "
            "removed, meshes over 4,000 triangles decimated, Z-up converted to Y-up, "
            "joints extracted to manifest.json. See NOTICE.md."
        ),
    },
}


def item_of(row: dict[str, object]) -> str | None:
    """Returns the item folder of a metadata row ("<tier>/<item>/<file>"), or None."""
    parts = str(row.get("file_name", "")).split("/")
    return parts[1] if len(parts) >= 3 else None


def filter_metadata(folder: Path) -> int:
    """Keeps only metadata.jsonl rows whose item we mirrored (present under objects/).

    Returns:
        rows kept
    """
    meta = folder / "metadata.jsonl"
    if not meta.exists():
        return 0
    kept_items = {p.name for p in (folder / "objects").iterdir()}
    rows = [json.loads(line) for line in meta.read_text().splitlines() if line.strip()]
    # Match on the item folder in file_name ("<tier>/<item>/<file>"): ids differ
    # in format between sources (Kenney uses "kit/name", folders use "kit__name").
    kept = [r for r in rows if item_of(r) in kept_items]
    if not kept:
        raise RuntimeError(f"{meta}: no rows match the mirrored items; not overwriting")
    meta.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept))
    return len(kept)


def credit_table(folder: Path) -> str:
    """Per-item credit table for attribution licenses (CC-BY): title, artist, original.

    CC-BY requires crediting each creator, and for Objaverse each model has its
    own Sketchfab artist, so the table is generated from the filtered metadata.
    """
    meta = folder / "metadata.jsonl"
    if not meta.exists():
        return ""
    rows = sorted(
        (json.loads(line) for line in meta.read_text().splitlines() if line.strip()),
        key=lambda r: str(r.get("id", "")),
    )
    lines = [
        "",
        "## Credits",
        "",
        "| Item | Title | Creator | Original | License |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        creator = r.get("authors", "")
        if r.get("author_url"):
            creator = f"[{creator}]({r['author_url']})"
        original = f"[link]({r['source_url']})" if r.get("source_url") else ""
        cells = [f"`{item_of(r)}`", r.get("title", ""), creator, original, r.get("license", "")]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def attribution(src: MirrorSource, items: int) -> str:
    """Builds the ATTRIBUTION.md text for one mirrored source."""
    excluded = src.get("exclude_items", [])
    why = src.get("_exclude_items_why", "")
    renames = src.get("rename_items", {})
    renamed = (
        "renamed item folders and files to drop real brand names ("
        + ", ".join(f"`{old}` → `{new}`" for old, new in renames.items())
        + "); file contents are unchanged. "
        if renames
        else "nothing in the files themselves. "
    )
    return f"""# {src["id"]}: attribution

**What:** {src["what"]}.

**Created by:** {src["creator"]}. Original: {src["creator_url"]}

**Converted to web-ready GLB by:** {src["converted_by"]}, in the Hugging Face dataset
[`{src["repo"]}`](https://huggingface.co/datasets/{src["repo"]}), mirrored here at revision
`{src["revision"]}`. Their original card is kept as `SOURCE_README.md`.

**License:** {src["license"]}. The full text is in `LICENSE` (and `LICENSES.md`, from the source).

**What we kept:** {items} items, tiers: {", ".join(f"`{t}/`" for t in src["tiers"])}.
Kept item names start with: {", ".join(f"`{p}`" for p in src["include_prefixes"] if p) or "(all)"}.
{f"Excluded: {', '.join(f'`{e}`' for e in excluded)}. {why}" if excluded else ""}

**What we changed:** {renamed}`metadata.jsonl` is filtered to
the items kept; rows still point at upstream tiers (`engine/`, `thumbs/`, `objects_ktx2/`)
that aren't mirrored here, and those remain available in the source dataset.

**Note for three.js:** `objects/` files use meshopt compression. Call
`gltfLoader.setMeshoptDecoder(MeshoptDecoder)` (from `three/addons/libs/meshopt_decoder.module.js`).
"""


def copy_own(name: str, spec: dict[str, str], out: Path) -> int:
    """Copies one of this repo's asset sets into the dataset with an ATTRIBUTION.md.

    Returns:
        files copied
    """
    dest = out / name
    shutil.copytree(ASSETS_DIR / spec["from"], dest, dirs_exist_ok=True)
    (dest / "ATTRIBUTION.md").write_text(
        f"# {name}: attribution\n\n**What:** {spec['what']}.\n\n"
        f"**Created by:** {spec['creator']}.\n\n**License:** {spec['license']} "
        f"(licence file in this folder).\n\n**What we changed:** {spec['changes']}\n"
    )
    return sum(1 for p in dest.rglob("*") if p.is_file())


CARD_DIR: Path = REPO_ROOT / "dataset_card"


def copy_cards(out: Path) -> int:
    """Copies the hand-written card and per-folder attribution files from dataset_card/.

    Returns:
        files copied
    """
    files = [p for p in CARD_DIR.rglob("*") if p.is_file()]
    for p in files:
        dest = out / p.relative_to(CARD_DIR)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest)
    return len(files)


def apply_renames(folder: Path, renames: dict[str, str]) -> int:
    """Renames item folders and files (every tier) and rewrites metadata paths.

    Used to strip real brand names from upstream folder names. Idempotent: an
    item already renamed is skipped. Metadata rows keep their original `title`,
    so credits still name the original work.

    Returns:
        items renamed
    """
    done = 0
    for old, new in renames.items():
        for tier in [p for p in folder.iterdir() if p.is_dir()]:
            src = tier / old
            if not src.exists():
                continue
            for f in src.iterdir():
                f.rename(src / f.name.replace(old, new))
            src.rename(tier / new)
            done += 1
    meta = folder / "metadata.jsonl"
    if meta.exists() and renames:
        text = meta.read_text()
        for old, new in renames.items():
            text = text.replace(old, new)
        meta.write_text(text)
    return done


def build(out: Path = MIRROR_DIR) -> dict[str, int]:
    """Finishes the staging folder: filtered metadata, attribution files, own sets.

    Returns:
        items or files per folder, for the summary table
    """
    counts: dict[str, int] = {}
    for src in load_plan():
        folder = out / src["id"]
        # Keep the upstream card for provenance, under a name that can't be
        # mistaken for this folder's own description.
        if (folder / "README.md").exists():
            (folder / "README.md").replace(folder / "SOURCE_README.md")
        apply_renames(folder, src.get("rename_items", {}))
        kept = filter_metadata(folder)
        items = sum(1 for _ in (folder / "objects").iterdir())
        text = attribution(src, items)
        if src["license"].startswith("CC-BY"):
            text += credit_table(folder)
        (folder / "ATTRIBUTION.md").write_text(text)
        counts[src["id"]] = kept or items
        print(f"{src['id']}: {items} items, metadata rows kept {kept}")
    for name, spec in OWN_SETS.items():
        counts[name] = copy_own(name, spec, out)
        print(f"{name}: {counts[name]} files copied")
    # Hand-written cards last, so they win over anything generated above.
    print(f"cards: {copy_cards(out)} files from dataset_card/")
    return counts


# Left behind by huggingface_hub downloads into local_dir; never upload them.
IGNORE_ON_UPLOAD: list[str] = [".cache/**", "**/.cache/**", "**/.DS_Store"]


# Remote paths to remove on publish: items we dropped after an earlier upload
# (upload_folder only adds/updates files, it doesn't delete stale ones).
DELETE_ON_PUBLISH: list[str] = ["kenney/objects/car-kit__*"]


def publish(folder: Path = MIRROR_DIR, repo_id: str = HF_REPO) -> str:
    """Creates the public dataset repo if needed and uploads the staging folder.

    One commit for the whole folder. The Hub deduplicates file content, so
    re-running after an interruption or a small change only sends what's new.

    Returns:
        the dataset URL
    """
    api = HfApi()
    api.create_repo(repo_id, repo_type="dataset", exist_ok=True, private=False)
    api.upload_folder(
        repo_id=repo_id,
        repo_type="dataset",
        folder_path=folder,
        ignore_patterns=IGNORE_ON_UPLOAD,
        delete_patterns=DELETE_ON_PUBLISH,
        commit_message="Upload Grand Theft GPU assets",
    )
    return f"https://huggingface.co/datasets/{repo_id}"
