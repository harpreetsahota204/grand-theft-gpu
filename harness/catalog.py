"""Builds `assets/catalog.json`: one structured record per asset in `assets/`.

The catalog is what `buildoff inventory` (see `harness.inventory`) searches, so
agents can find assets without opening files. It is generated, never hand
edited: `buildoff assets catalog` rebuilds it, and `buildoff assets all` rebuilds
it after the asset sets themselves.

Output is deterministic: entries are sorted by id, numbers are rounded, and no
timestamps or absolute paths are written, so rebuilding unchanged assets
produces a byte-identical file.

Per-asset facts come from two places:
- the .glb itself (triangles, real-world size, named parts), read with trimesh
- each folder's sidecar data (USDCraft `manifest.json` for prop parts/joints,
  `scripts/usdcraft_props.csv` for the dataset group), plus a fixed table of
  per-category source and license
"""

import csv
import json
import re
import struct
from pathlib import Path
from typing import TypedDict

import trimesh

from harness.config import ASSETS_DIR, REPO_ROOT

CATALOG_PATH: Path = ASSETS_DIR / "catalog.json"
CATALOG_VERSION: int = 1

# Where each asset folder lands in a race workspace, as a URL the game fetches.
# Mirrors config.GAME_ASSETS_SUBDIR ("public/assets/gt-gpu"), served at "/".
URL_PREFIX: str = "/assets/gt-gpu"


class Source(TypedDict):
    """Provenance shared by every asset in one folder."""

    category: str
    source: str
    source_url: str
    license: str


# One row per asset folder. Folders not listed here are skipped, so a new pack
# must be registered before it appears in the catalog.
SOURCES: dict[str, Source] = {
    "gpu": Source(
        category="loot",
        source="Grab3D graphics card",
        source_url="https://grab3d.com/models/electronics/graphics-card/",
        license="CC0-1.0",
    ),
    "cars": Source(
        category="vehicle",
        source="Kenney Car Kit 3.1",
        source_url="https://kenney.nl/assets/car-kit",
        license="CC0-1.0",
    ),
    "props": Source(
        category="prop",
        source="NVIDIA USDCraft-10K (converted)",
        source_url="https://huggingface.co/datasets/nvidia/USDCraft-10K",
        license="Apache-2.0",
    ),
}

# Kenney car-kit files that are parts or track pieces rather than drivable vehicles.
CAR_PART_PREFIXES: tuple[str, ...] = ("debris-", "wheel-", "cone", "box")

# Synonyms appended as tags so plain-language searches hit the right asset
# ("cop" finds police, "server" finds rack hardware). Keyed by a substring of the id.
SYNONYMS: dict[str, list[str]] = {
    "police": ["cop", "cops", "pursuit", "chase"],
    "taxi": ["cab", "robotaxi"],
    "sedan": ["car", "robotaxi"],
    "suv": ["car", "robotaxi"],
    "ambulance": ["emergency"],
    "firetruck": ["emergency", "fire"],
    "server": ["datacenter", "data-center", "compute", "heist-target"],
    "rack": ["datacenter", "storage"],
    "safe": ["vault", "heist-target"],
    "atm": ["cash", "money", "heist-target"],
    "graphics-card": ["gpu", "loot", "heist-target", "h100"],
    "drone": ["quadcopter", "flying"],
    "robot": ["delivery", "autonomous"],
    "scooter": ["rideable", "micromobility"],
    "bicycle": ["bike", "rideable"],
    "laptop": ["computer", "loot"],
    "desktop": ["computer", "loot"],
    "traffic": ["street", "intersection"],
    "barrier": ["roadblock", "street"],
    "gate": ["entrance", "security"],
}


class Asset(TypedDict):
    """One catalog record. `buildoff inventory schema` documents every field."""

    id: str
    category: str
    kind: str
    name: str
    url: str
    repo_path: str
    format: str
    bytes: int
    triangles: int
    size_m: dict[str, float]
    parts: list[str]
    joints: list[dict[str, object]]
    tags: list[str]
    source: str
    source_url: str
    license: str


def tokens(text: str) -> list[str]:
    """Splits text into lowercase word tokens: "rack-mount_server" → rack, mount, server."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def inspect_glb(path: Path) -> tuple[int, dict[str, float], list[str]]:
    """Reads triangle count, bounding-box size and named geometry nodes from a .glb.

    Args:
        path: the .glb file

    Returns:
        (triangles, size in metres as {"x", "y", "z"} with y up, sorted part names)
    """
    scene = trimesh.load(path, force="scene")
    # nodes_geometry lists instanced nodes; count each instance's faces once.
    triangles = sum(
        len(scene.geometry[scene.graph[node][1]].faces) for node in scene.graph.nodes_geometry
    )
    x, y, z = (round(float(v), 3) for v in scene.extents)
    return triangles, {"x": x, "y": y, "z": z}, glb_mesh_node_names(path)


def glb_mesh_node_names(path: Path) -> list[str]:
    """Returns the names of glTF nodes that carry a mesh, read from the .glb's JSON chunk.

    Read directly rather than via trimesh, which appends random suffixes to
    nodes with several primitives and would make the catalog non-deterministic.
    """
    data = path.read_bytes()
    # GLB layout: 12-byte header, then chunk 0 = [length u32][type u32][JSON bytes].
    length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20 : 20 + length])
    return sorted({n["name"] for n in gltf.get("nodes", []) if "mesh" in n and n.get("name")})


def prop_metadata() -> dict[str, dict[str, object]]:
    """Loads USDCraft prop links, joints and dataset group, keyed by .glb file name."""
    manifest = json.loads((ASSETS_DIR / "props" / "manifest.json").read_text())
    groups: dict[str, str] = {}
    with (REPO_ROOT / "scripts" / "usdcraft_props.csv").open() as f:
        for row in csv.DictReader(f):
            # path looks like rigid/<group>/<category_id>_<category>/<variant>
            slug = re.sub(r"[^a-z0-9]+", "-", row["category"].lower()).strip("-")
            groups[f"{slug}.glb"] = row["path"].split("/")[1]
    return {
        p["file"]: {
            "links": p["links"],
            "joints": p["joints"],
            "group": groups.get(p["file"], ""),
            "name": p["category"],
        }
        for p in manifest["props"]
    }


def build_entry(folder: str, path: Path, props: dict[str, dict[str, object]]) -> Asset:
    """Builds one catalog record for a .glb.

    Args:
        folder: asset folder name (a key of SOURCES)
        path: the .glb inside that folder
        props: USDCraft sidecar data from `prop_metadata`

    Returns:
        the record
    """
    src = SOURCES[folder]
    stem = path.stem
    triangles, size_m, parts = inspect_glb(path)
    name = stem.replace("-", " ")
    joints: list[dict[str, object]] = []
    tags = set(tokens(stem)) | {src["category"]}

    # Category-specific refinements.
    if folder == "props":
        meta = props.get(path.name, {})
        name = str(meta.get("name", name))
        # Props' geometry nodes are generic ("Geom", "mesh"); the USD links are the movable parts.
        parts = sorted(meta.get("links", []))  # type: ignore[arg-type]
        joints = list(meta.get("joints", []))  # type: ignore[arg-type]
        if meta.get("group"):
            tags |= set(tokens(str(meta["group"])))
        if joints:
            tags.add("articulated")
    if folder == "cars":
        kind = "vehicle-part" if stem.startswith(CAR_PART_PREFIXES) else "vehicle"
    else:
        kind = src["category"]
    for key, extra in SYNONYMS.items():
        if key in stem:
            tags |= set(extra)

    return Asset(
        id=f"{folder}/{stem}",
        category=src["category"],
        kind=kind,
        name=name,
        url=f"{URL_PREFIX}/{folder}/{path.name}",
        repo_path=str(path.relative_to(REPO_ROOT)),
        format="glb",
        bytes=path.stat().st_size,
        triangles=triangles,
        size_m=size_m,
        parts=parts,
        joints=joints,
        tags=sorted(tags),
        source=src["source"],
        source_url=src["source_url"],
        license=src["license"],
    )


def build_catalog() -> dict[str, object]:
    """Builds the full catalog from every registered asset folder in assets/.

    Returns:
        the catalog document: {"version", "url_prefix", "count", "assets": [...]}
    """
    props = prop_metadata()
    entries = [
        build_entry(folder, glb, props)
        for folder in sorted(SOURCES)
        for glb in sorted((ASSETS_DIR / folder).glob("*.glb"))
    ]
    entries.sort(key=lambda e: e["id"])
    return {
        "version": CATALOG_VERSION,
        "url_prefix": URL_PREFIX,
        "count": len(entries),
        "assets": entries,
    }


def write_catalog(path: Path = CATALOG_PATH) -> int:
    """Builds the catalog and writes it as stable, pretty-printed JSON.

    Returns:
        number of assets written
    """
    catalog = build_catalog()
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")
    return int(catalog["count"])  # type: ignore[call-overload]
