"""Builds `assets/catalog.json`: one structured record per asset in the HF dataset.

The asset dataset (harpreetsahota/grand-theft-gpu-assets) is the source of
truth; this catalog indexes it so `buildoff inventory` (and the racing models'
`tools/assets.mjs`) can search ~1,200 assets without opening any files. It is
generated from the local staging copy (`config.MIRROR_DIR`) by
`buildoff assets catalog`, and is never hand edited.

Every record's `hf_path` is its path inside the dataset, and its `url` is where
a game loads it inside a race workspace: `/assets/gt-gpu/<hf_path>` (the
workspace mirrors the dataset layout under `public/assets/gt-gpu/`).

Per-asset facts come from:
- upstream `metadata.jsonl` (Rocketbox, Kenney): their files are meshopt
  compressed, which trimesh can't decode, so triangles/bones/sizes come from there
- the .glb itself for our own sets (GPU, USDCraft props): triangles, size, parts
- USDCraft `manifest.json` for prop joints, and glTF JSON for clip names

Output is deterministic: sorted ids, rounded numbers, no timestamps or absolute
paths, and strict JSON (no Infinity/NaN), so unchanged inputs give a
byte-identical file.
"""

import json
import re
import struct
from pathlib import Path
from typing import Any

import trimesh

from harness.config import ASSETS_DIR, HF_ASSETS_REPO, HF_ASSETS_REVISION, MIRROR_DIR

CATALOG_PATH: Path = ASSETS_DIR / "catalog.json"
CATALOG_VERSION: int = 2

# The dataset is mirrored under this URL path inside each race workspace.
URL_PREFIX: str = "/assets/gt-gpu"

# Tiers that are fetched on demand rather than seeded into every workspace.
OPTIONAL_TIERS: tuple[str, ...] = ("lods", "mobile", "collision")

# Plain-language synonyms appended as tags, keyed by a substring of the asset id,
# so "cop", "vc" or "phone call" find the right thing.
SYNONYMS: dict[str, list[str]] = {
    # vehicles
    "police": ["cop", "cops", "pursuit", "chase"],
    "taxi": ["cab", "robotaxi"],
    "sedan": ["car", "robotaxi"],
    "suv": ["car", "robotaxi"],
    "ambulance": ["emergency"],
    "firetruck": ["emergency"],
    # loot and props
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
    # people
    "business": ["vc", "investor", "founder", "executive", "suit", "office"],
    "security": ["guard", "bouncer"],
    "construction": ["worker", "builder", "hardhat"],
    "medical": ["doctor", "nurse", "hospital"],
    "chef": ["cook", "restaurant"],
    "delivery": ["courier", "driver"],
    "military": ["soldier"],
    "pilot": ["airline"],
    "fire-": ["firefighter"],
    "adult": ["pedestrian", "civilian", "npc", "crowd"],
    "wood-": ["woodworker", "carpenter", "worker"],
    "gardener": ["worker"],
    # city pieces (Kenney kits name buildings "building-a", so map the kits to plain words)
    "city-kit-commercial": ["office", "shop", "store", "downtown", "commercial-building"],
    "skyscraper": ["tower", "office", "highrise"],
    "city-kit-suburban": ["house", "home", "residential"],
    "city-kit-industrial": ["factory", "warehouse", "industrial-building"],
    "modular-buildings": ["building", "facade"],
    "retro-urban-kit": ["urban", "street", "downtown"],
    "furniture-kit": ["furniture", "interior", "office"],
    "city-kit-roads": ["road", "street"],
    # motions
    "cell": ["phone", "call", "texting"],
    "gestic": ["talk", "talking", "gesture", "pitch", "conversation"],
    "idle": ["standing", "waiting"],
    "dancing": ["dance", "party"],
    "-sit": ["sitting", "seated"],
    "cheer": ["celebrate", "celebration"],
    "drunk": ["party"],
}


def tokens(text: str) -> list[str]:
    """Splits text into lowercase word tokens: "rack-mount_server" → rack, mount, server."""
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def synonyms(key: str) -> set[str]:
    """Returns synonym tags for every SYNONYMS key found in `key`."""
    return {tag for k, tags in SYNONYMS.items() if k in key for tag in tags}


def gltf_json(path: Path) -> dict[str, Any]:
    """Reads the JSON chunk of a .glb without decoding any geometry."""
    data = path.read_bytes()
    # GLB layout: 12-byte header, then chunk 0 = [length u32][type u32][JSON bytes].
    length = struct.unpack_from("<I", data, 12)[0]
    return json.loads(data[20 : 20 + length])


def mesh_node_names(gltf: dict[str, Any]) -> list[str]:
    """Names of glTF nodes that carry a mesh (stable, unlike trimesh's suffixed names)."""
    return sorted({n["name"] for n in gltf.get("nodes", []) if "mesh" in n and n.get("name")})


def triangles_from_json(gltf: dict[str, Any]) -> int:
    """Counts triangles from accessor counts (indices / 3, or vertices / 3)."""
    acc = gltf.get("accessors", [])
    total = 0
    for mesh in gltf.get("meshes", []):
        for prim in mesh["primitives"]:
            if "indices" in prim:
                total += acc[prim["indices"]]["count"] // 3
            else:
                total += acc[prim["attributes"]["POSITION"]]["count"] // 3
    return total


def inspect_glb(path: Path) -> tuple[int, dict[str, float], list[str]]:
    """Reads triangles, bounding-box size (metres, y up) and part names from a plain .glb."""
    scene = trimesh.load(path, force="scene")
    triangles = sum(
        len(scene.geometry[scene.graph[node][1]].faces) for node in scene.graph.nodes_geometry
    )
    x, y, z = (round(float(v), 3) for v in scene.extents)
    return triangles, {"x": x, "y": y, "z": z}, mesh_node_names(gltf_json(path))


def record(
    *,
    hf_path: str,
    category: str,
    kind: str,
    name: str,
    root: Path,
    license_id: str,
    source: str,
    source_url: str,
    tags: set[str],
    id_tags: bool = True,
    item: str = "",
    **fields: Any,
) -> dict[str, Any]:
    """Builds one catalog record with the shared fields; extra fields pass through.

    `id_tags=False` keeps words from the file id out of the tags, for items whose
    original file names carry real brand names or hashes (vehicles).
    `item` overrides the id's item part, for sets whose files share one folder
    (Kenney sound and sprite families).
    """
    if not item:
        item = hf_path.split("/")[-2] if hf_path.count("/") >= 2 else Path(hf_path).stem
    folder = hf_path.split("/")[0]
    rec: dict[str, Any] = {
        "id": f"{folder}/{item}",
        "category": category,
        "kind": kind,
        "name": name,
        "hf_path": hf_path,
        "url": f"{URL_PREFIX}/{hf_path}",
        "seeded": True,
        "bytes": (root / hf_path).stat().st_size,
        "triangles": None,
        "size_m": None,
        "parts": [],
        "joints": [],
        "animations": [],
        "group": "",
        # Synonyms match against the whole dataset path, so kit names count too.
        "tags": sorted(
            tags | {category, kind} | (set(tokens(item)) | synonyms(hf_path) if id_tags else set())
        ),
        "license": license_id,
        "source": source,
        "source_url": source_url,
    }
    rec.update(fields)
    return rec


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Reads a JSON Lines file into a list of dicts."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def people(root: Path) -> list[dict[str, Any]]:
    """Rocketbox avatars: one record per person, web tier seeded, other tiers listed."""
    out = []
    for row in read_jsonl(root / "rocketbox-avatars" / "metadata.jsonl"):
        pid = row["id"]
        tiers = {
            t: f"rocketbox-avatars/{p}"
            for t, p in (
                ("lods", f"lods/{pid}/{pid}_lod1.glb"),
                ("mobile", f"mobile/{pid}/{pid}.glb"),
                ("collision", f"collision/{pid}/{pid}_collision.glb"),
            )
            if (root / "rocketbox-avatars" / p).exists()
        }
        out.append(
            record(
                hf_path=f"rocketbox-avatars/objects/{pid}/{pid}.glb",
                category="person",
                kind=row.get("kind", "person"),
                name=row["title"],
                root=root,
                license_id="MIT",
                source="Microsoft Rocketbox (web conversion: codepawl)",
                source_url=row.get("source_url", ""),
                tags={"rigged", "biped"},
                triangles=row.get("triangles"),
                group=row.get("group", ""),
                bones=row.get("bones"),
                blendshapes=row.get("blendshapes"),
                optional_tiers=tiers,
            )
        )
    return out


def motions(root: Path) -> list[dict[str, Any]]:
    """Rocketbox motion clips: one record per clip (avatar with the clip baked on)."""
    out = []
    for row in read_jsonl(root / "rocketbox-motions" / "metadata.jsonl"):
        cid = row["id"]
        out.append(
            record(
                hf_path=f"rocketbox-motions/objects/{cid}/{cid}.glb",
                category="motion",
                kind=row.get("style", "motion"),
                name=row["title"],
                root=root,
                license_id="MIT",
                source="Microsoft Rocketbox (web conversion: codepawl)",
                source_url=row.get("source_url", ""),
                tags={"animation", "mocap", row.get("gender", "")} - {""},
                triangles=row.get("triangles"),
                animations=[{"name": cid, "seconds": row.get("seconds"), "fps": row.get("fps")}],
                group=row.get("style", ""),
                plays_on="any rocketbox-avatars person (shared 3ds Max Biped skeleton)",
            )
        )
    return out


def kenney(root: Path) -> list[dict[str, Any]]:
    """Kenney city pieces (buildings, roads, urban kit, furniture); the car kit is excluded."""
    out = []
    for row in read_jsonl(root / "kenney" / "metadata.jsonl"):
        item = row["file_name"].split("/")[1]
        kit = row.get("kit_slug", "")
        su = row.get("size_units")
        out.append(
            record(
                hf_path=f"kenney/objects/{item}/{item}.glb",
                category="city",
                kind=kit,
                name=row["title"],
                root=root,
                license_id="CC0-1.0",
                source=f"Kenney {row.get('kit', kit)} (web conversion: codepawl)",
                source_url=row.get("source_url", ""),
                tags=set(tokens(kit)),
                triangles=row.get("triangles"),
                # Kenney's model units are close to metres but not guaranteed.
                size_m={"x": su[0], "y": su[1], "z": su[2]} if su else None,
                group=row.get("kit", ""),
            )
        )
    return out


# Generic names for vehicles whose original titles name a real manufacturer or
# model (the game uses no real brands). Original titles stay in ATTRIBUTION.md.
VEHICLE_NAMES: dict[str, tuple[str, str]] = {
    "police-sedan-692c68c4": ("police sedan", "police"),
    "taxi-sedan-210f95a0": ("taxi sedan", "taxi"),
    "british-compact-car-low-poly-model-f1e9c43c": ("compact car", "car"),
    "british-compact-car-low-poly-model-e9dd83b4": ("compact van", "van"),
    "low-poly-car-6cee6dbd": ("sedan", "car"),
    "classic-muscle-car-641efc88": ("muscle car", "car"),
    "muscle-low-poly-011ebf82": ("convertible muscle car", "car"),
    "french-delivery-van-a350a422": ("delivery van", "van"),
    "ambulance-van-f3daf79e": ("ambulance van", "emergency"),
    "fire-truck-e0fadd42": ("fire truck", "emergency"),
    "city-bus-050e8acd": ("city bus", "bus"),
    "japanese-mini-truck-d5d93879": ("mini pickup truck", "truck"),
    "fancy-car-780c75b7": ("vintage sedan", "car"),
    "cars__SUV": ("SUV", "car"),
    "cars__Taxi": ("taxi", "taxi"),
}

VEHICLE_SOURCES: dict[str, tuple[str, str, str]] = {
    "vehicles-objaverse": ("CC-BY-4.0", "Objaverse (credit the artist; see ATTRIBUTION.md)", ""),
    "vehicles-quaternius": ("CC0-1.0", "Quaternius Cars Pack (web conversion: codepawl)", ""),
}


def vehicles(root: Path) -> list[dict[str, Any]]:
    """Hand-picked realistic vehicles (Objaverse + Quaternius), with generic names."""
    out = []
    for folder, (license_id, source, _) in VEHICLE_SOURCES.items():
        for row in read_jsonl(root / folder / "metadata.jsonl"):
            item = row["file_name"].split("/")[1]
            name, kind = VEHICLE_NAMES.get(item, (row.get("title", item), "car"))
            tiers = {
                t: f"{folder}/{t}/{item}/{item}{suffix}.glb"
                for t, suffix in (("lods", "_lod1"), ("collision", "_collision"))
                if (root / folder / t / item / f"{item}{suffix}.glb").exists()
            }
            out.append(
                record(
                    hf_path=f"{folder}/objects/{item}/{item}.glb",
                    category="vehicle",
                    kind=kind,
                    name=name,
                    root=root,
                    license_id=license_id,
                    source=f"{row.get('authors', '')} · {source}",
                    source_url=row.get("source_url", ""),
                    tags={"vehicle", "drivable", *tokens(name)} | synonyms(name),
                    id_tags=False,
                    triangles=row.get("triangles"),
                    optional_tiers=tiers,
                )
            )
    return out


def own_sets(root: Path) -> list[dict[str, Any]]:
    """Our GPU and USDCraft props: inspected directly (plain, uncompressed glb)."""
    out = []
    gpu = root / "gpu" / "graphics-card-light.glb"
    tris, size, parts = inspect_glb(gpu)
    out.append(
        record(
            hf_path="gpu/graphics-card-light.glb",
            category="loot",
            kind="loot",
            name="graphics card",
            root=root,
            license_id="CC0-1.0",
            source="Grab3D",
            source_url="https://grab3d.com/models/electronics/graphics-card/",
            tags=set(),
            triangles=tris,
            size_m=size,
            parts=parts,
        )
    )
    manifest = json.loads((root / "usdcraft-props" / "manifest.json").read_text())
    for p in manifest["props"]:
        tris, size, _ = inspect_glb(root / "usdcraft-props" / p["file"])
        out.append(
            record(
                hf_path=f"usdcraft-props/{p['file']}",
                category="prop",
                kind="prop",
                name=p["category"],
                root=root,
                license_id="Apache-2.0",
                source="NVIDIA USDCraft-10K (converted)",
                source_url="https://huggingface.co/datasets/nvidia/USDCraft-10K",
                tags={"articulated"} if p["joints"] else set(),
                triangles=tris,
                size_m=size,
                parts=sorted(p["links"]),
                joints=p["joints"],
                group=p["source_path"].split("/")[1],
            )
        )
    return out


def animation_libraries(root: Path) -> list[dict[str, Any]]:
    """Quaternius clip libraries and mannequin: clip names read from glTF JSON."""
    out = []
    for glb in sorted((root / "quaternius-animations").glob("*.glb")):
        gj = gltf_json(glb)
        clips = sorted(a.get("name", "") for a in gj.get("animations", []))
        out.append(
            record(
                hf_path=f"quaternius-animations/{glb.name}",
                category="animation" if clips else "person",
                kind="clip-library" if clips else "mannequin",
                name=glb.stem.replace("-", " "),
                root=root,
                license_id="CC0-1.0",
                source="Quaternius Universal Animation Library",
                source_url="https://quaternius.com/packs/universalanimationlibrary.html",
                tags={"rigged", "walk", "run", "locomotion"} if clips else {"rigged"},
                triangles=triangles_from_json(gj),
                animations=[{"name": c} for c in clips],
                plays_on="the Quaternius humanoid rig; retarget for Rocketbox people",
            )
        )
    return out


def bodies(root: Path) -> list[dict[str, Any]]:
    """Meta MHR base bodies: fetched on demand (large; no clothes or textures)."""
    out = []
    for glb in sorted((root / "meta-mhr").glob("*.glb")):
        gj = gltf_json(glb)
        targets = max(
            (len(p.get("targets", [])) for m in gj.get("meshes", []) for p in m["primitives"]),
            default=0,
        )
        rec = record(
            hf_path=f"meta-mhr/{glb.name}",
            category="body",
            kind="parametric-body",
            name=f"MHR body {glb.stem.split('-')[-1]}",
            root=root,
            license_id="Apache-2.0",
            source="Meta MHR (Momentum Human Rig)",
            source_url="https://github.com/facebookresearch/MHR",
            tags={"rigged", "blendshapes", "base-body"},
            triangles=triangles_from_json(gj),
            morph_targets=targets,
        )
        rec["seeded"] = False
        out.append(rec)
    return out


def city(root: Path) -> list[dict[str, Any]]:
    """The SF slice scene plus its data files, as one map record."""
    meta = json.loads((root / "sf-city" / "meta.json").read_text())
    return [
        record(
            hf_path="sf-city/sf-city.glb",
            category="map",
            kind="city",
            name="San Francisco: SoMa, Financial District, Embarcadero",
            root=root,
            license_id="ODbL-1.0",
            source="OpenStreetMap + USGS 3DEP elevation (built by grand-theft-gpu)",
            source_url="https://www.openstreetmap.org/copyright",
            tags={"san-francisco", "sf", "terrain", "hills", "streets", "buildings", "map"},
            # Layers are separate meshes with named materials and metre UVs (meta["uv"]).
            parts=meta.get("layers", []),
            uv=meta.get("uv", ""),
            data_files={
                "buildings": f"{URL_PREFIX}/sf-city/buildings.json",
                "streets": f"{URL_PREFIX}/sf-city/streets.json",
                "meta": f"{URL_PREFIX}/sf-city/meta.json",
            },
            axes=meta["axes"],
        )
    ]


def info_records(folder: Path) -> list[dict[str, Any]]:
    """Reads every item's info.json in a media folder, sorted by item id."""
    return [json.loads(f.read_text()) for f in sorted(folder.glob("*/info.json"))]


def media_url(hf_path: str) -> str:
    """Workspace URL for a dataset path (what TextureLoader/Audio/FontFace load)."""
    return f"{URL_PREFIX}/{hf_path}"


def skies(root: Path) -> list[dict[str, Any]]:
    """Poly Haven HDRIs: the 1k file is seeded; the 2k file is an optional tier."""
    out = []
    for info in info_records(root / "polyhaven-hdris"):
        hid, files = info["id"], info["files"]
        seeded = info["seeded_resolution"]
        out.append(
            record(
                hf_path=f"polyhaven-hdris/{hid}/{files[seeded]['file']}",
                category="sky",
                kind="hdri",
                name=info["what"],
                root=root,
                license_id=info["license"],
                source="Poly Haven",
                source_url=info["source"],
                tags={"hdri", "environment", "lighting", "skybox", *tokens(info["what"])},
                optional_tiers={
                    res: f"polyhaven-hdris/{hid}/{f['file']}"
                    for res, f in files.items()
                    if res != seeded
                },
            )
        )
    return out


# ambientCG map names → the same role names Poly Haven items use.
MAP_ROLES: dict[str, str] = {
    "Color": "color",
    "NormalGL": "normal_gl",
    "Roughness": "roughness",
    "AmbientOcclusion": "ao",
    "Metalness": "metalness",
    "Emission": "emission",
    "Opacity": "opacity",
}


def textures(root: Path) -> list[dict[str, Any]]:
    """PBR surface textures (Poly Haven + ambientCG): one record per material."""
    out = []
    for folder, source in (
        ("polyhaven-textures", "Poly Haven"),
        ("ambientcg-textures", "ambientCG"),
    ):
        for info in info_records(root / folder):
            tid = info["id"]
            maps = {
                MAP_ROLES.get(role, role): media_url(f"{folder}/{tid}/{m['file']}")
                for role, m in sorted(info["maps"].items())
            }
            color = info["maps"].get("color") or info["maps"]["Color"]
            # Emission maps mark night facades with lit windows.
            extra = {"night", "lit", "emissive"} if "emission" in maps else set()
            out.append(
                record(
                    hf_path=f"{folder}/{tid}/{color['file']}",
                    category="texture",
                    kind="pbr",
                    name=info["what"],
                    root=root,
                    license_id=info["license"],
                    source=source,
                    source_url=info["source"],
                    tags={"material", "surface", *tokens(info["what"]), *tokens(tid)} | extra,
                    id_tags=False,
                    maps=maps,
                    tile_m=info.get("size_m"),
                )
            )
    return out


def trees(root: Path) -> list[dict[str, Any]]:
    """Google Poly trees (CC-BY-3.0: credit each artist; see ATTRIBUTION.md)."""
    out = []
    for row in read_jsonl(root / "trees-google-poly" / "metadata.jsonl"):
        item = row["file_name"].split("/")[1]
        kind = "palm" if "palm" in item else "tree"
        ext = row.get("original_extents")
        scale = row.get("scale") or 1.0
        out.append(
            record(
                hf_path=f"trees-google-poly/objects/{item}/{item}.glb",
                category="nature",
                kind=kind,
                name=row["title"].lower(),
                root=root,
                license_id=row.get("license", "CC-BY-3.0"),
                source=f"{row.get('authors', '')} · Google Poly (web conversion: codepawl)",
                source_url=row.get("source_url", ""),
                tags={"tree", "plant", "vegetation", "street", "park", *tokens(row["title"])},
                id_tags=False,
                triangles=row.get("triangles"),
                notes=(
                    "Normalised to about 1 m tall: scale up to real size "
                    "(street trees 8-12 m, palms 10-20 m)."
                ),
                # codepawl rescaled each model by `scale`; extents are pre-scale.
                size_m={k: round(v * scale, 3) for k, v in zip("xyz", ext, strict=True)}
                if ext
                else None,
            )
        )
    return out


def family_of(path: Path) -> str:
    """Groups numbered variants: "impactGlass_heavy_003.ogg" → "impactGlass_heavy"."""
    return re.sub(r"_\d+$", "", path.stem)


def split_camel(name: str) -> list[str]:
    """Search words from a Kenney file family: "impactGlass_heavy" → impact, glass, heavy."""
    return tokens(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name))


def media_sets(root: Path) -> list[dict[str, Any]]:
    """Sounds, particle sprites and fonts: one record per sound/sprite family or font."""
    out = []
    oga = root / "audio-opengameart"
    for info in info_records(oga):
        paths = [f"audio-opengameart/{info['id']}/{f}" for f in sorted(info["files"])]
        audio = [p for p in paths if p.endswith((".ogg", ".wav"))]
        out.append(
            record(
                hf_path=audio[0],
                category="sound",
                kind="loop" if "loop" in info["id"] or "ambience" in info["id"] else "sfx",
                name=info["what"],
                root=root,
                license_id=info["license"],
                source=f"{info['author']} · OpenGameArt",
                source_url=info["source"],
                tags={"audio", "sound", *tokens(info["what"])},
                files=[media_url(p) for p in audio],
            )
        )
    kenney_media = root / "kenney-media"
    for pack, category, suffix in (
        ("impact-sounds", "sound", ".ogg"),
        ("interface-sounds", "sound", ".ogg"),
        ("particle-pack", "vfx", ".png"),
    ):
        info = json.loads((kenney_media / pack / "info.json").read_text())
        # Only top-level files: the particle pack's Rotated/ copies stay out of the index.
        files = sorted(f for f in (kenney_media / pack).glob(f"*{suffix}"))
        families: dict[str, list[Path]] = {}
        for f in files:
            families.setdefault(family_of(f), []).append(f)
        for fam, members in sorted(families.items()):
            words = split_camel(fam)
            rels = [f"kenney-media/{pack}/{m.name}" for m in members]
            out.append(
                record(
                    hf_path=rels[0],
                    category=category,
                    kind="sprite" if category == "vfx" else pack.removesuffix("-sounds"),
                    name=" ".join(words),
                    root=root,
                    license_id=info["license"],
                    source=f"Kenney {pack}",
                    source_url=info["source"],
                    tags={"audio", "sound"} if category == "sound" else {"particle", "sprite"},
                    group=pack,
                    item=f"{pack}/{fam}",
                    files=[media_url(r) for r in rels],
                )
            )
    for info in info_records(root / "google-fonts"):
        fonts = [
            f"google-fonts/{info['id']}/{f}" for f in sorted(info["files"]) if f.endswith(".ttf")
        ]
        out.append(
            record(
                hf_path=fonts[0],
                category="font",
                kind="ttf",
                name=info["what"],
                root=root,
                license_id=info["license"],
                source="Google Fonts",
                source_url=info["source"],
                tags={"font", "typeface", "hud", "text", *tokens(info["what"])},
                files=[media_url(f) for f in fonts],
            )
        )
    return out


def build_catalog(root: Path = MIRROR_DIR) -> dict[str, Any]:
    """Builds the full catalog from the staged dataset folder.

    Returns:
        {"version", "dataset", "revision", "url_prefix", "count", "assets": [...]}
    """
    entries = (
        people(root)
        + motions(root)
        + kenney(root)
        + vehicles(root)
        + own_sets(root)
        + animation_libraries(root)
        + bodies(root)
        + city(root)
        + skies(root)
        + textures(root)
        + trees(root)
        + media_sets(root)
    )
    entries.sort(key=lambda e: e["id"])
    ids = [e["id"] for e in entries]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate asset ids in catalog")
    return {
        "version": CATALOG_VERSION,
        "dataset": HF_ASSETS_REPO,
        "revision": HF_ASSETS_REVISION,
        "url_prefix": URL_PREFIX,
        "count": len(entries),
        "assets": entries,
    }


def write_catalog(path: Path = CATALOG_PATH) -> int:
    """Builds the catalog and writes it as stable, strict, pretty-printed JSON.

    Returns:
        number of assets written
    """
    catalog = build_catalog()
    # allow_nan=False: JSON has no Infinity/NaN, and browsers' JSON.parse rejects them.
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return int(catalog["count"])
