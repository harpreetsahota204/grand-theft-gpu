"""Converts curated NVIDIA USDCraft-10K props from OpenUSD to game-ready .glb files.

USDCraft ships Isaac Sim stages (`physx/model.usdc`, Z-up, metres) that three.js
can't load. This script runs inside Blender, which has a full USD importer and a
glTF exporter, and writes one `.glb` per prop into `assets/props/`, plus a
`manifest.json` describing each prop and its joints.

Per prop it:
1. imports only render geometry (collision meshes have USD purpose "guide" and are skipped)
2. decimates any mesh above `MAX_TRIS_PER_MESH` so a scene of ~45 props stays light
3. keeps each USD link (chassis, door, lid...) as its own node so the game can animate it
4. reads the USD physics joints (revolute/prismatic) with Blender's bundled `pxr`
   and records parent link, child link, axis and limits in the manifest
5. exports Y-up glTF binary (the exporter converts from Blender's Z-up)

Run (from the repo root):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        --python scripts/convert_usdcraft.py -- <picked.csv> <raw_dir> <out_dir>

`picked.csv` has columns category,object_id,path,has_textures,joint_types and is
produced while curating the prop list (see AGENT_ONBOARDING.md, section 1b).
"""

import csv
import json
import re
import sys
from pathlib import Path
from typing import TypedDict

import bpy  # type: ignore[import-not-found]  # only importable inside Blender
import mathutils  # type: ignore[import-not-found]  # Blender-only math module
from pxr import Usd, UsdPhysics  # type: ignore[import-not-found]  # Blender bundles pxr

# Per-mesh triangle cap. Most USDCraft parts are boxes (12 tris); a few
# procedural parts (vent grilles, front panels) run to 65K, which is far past
# the PS2-era look and too heavy for dozens of props in a browser.
MAX_TRIS_PER_MESH: int = 4000

# Joint prim types we record; spherical joints exist in only 5 objects dataset-wide.
JOINT_TYPES: dict[str, str] = {
    "PhysicsRevoluteJoint": "revolute",
    "PhysicsPrismaticJoint": "prismatic",
}


class JointInfo(TypedDict):
    """One articulation between two links, in USD stage units (metres, degrees).

    Axis is the USD joint axis letter in the Z-up source frame; the game
    must map it to Y-up (USD Z → glTF Y, USD Y → glTF -Z).
    """

    name: str
    type: str
    parent_link: str
    child_link: str
    axis: str
    lower: float | None
    upper: float | None


class PropEntry(TypedDict):
    """Manifest row for one converted prop."""

    file: str
    category: str
    source_object_id: str
    source_path: str
    triangles: int
    size_m: list[float]
    links: list[str]
    joints: list[JointInfo]


def slugify(text: str) -> str:
    """Turns a category name like 'ATM Machine' into a filename slug 'atm-machine'."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def read_joints(usd_path: Path) -> list[JointInfo]:
    """Reads revolute and prismatic joints from a USDCraft stage.

    Args:
        usd_path: the prop's `physx/model.usdc`

    Returns:
        one entry per supported joint; link names are the last path element
        of body0 (parent) and body1 (child), matching the node names in the .glb
    """
    stage = Usd.Stage.Open(str(usd_path))
    joints: list[JointInfo] = []
    for prim in stage.Traverse():
        kind = JOINT_TYPES.get(prim.GetTypeName())
        if kind is None:
            continue
        joint = UsdPhysics.Joint(prim)
        body0 = joint.GetBody0Rel().GetTargets()
        body1 = joint.GetBody1Rel().GetTargets()
        # Revolute and prismatic share axis/lower/upper attribute names.
        joints.append(
            JointInfo(
                name=prim.GetName(),
                type=kind,
                parent_link=body0[0].name if body0 else "",
                child_link=body1[0].name if body1 else "",
                axis=str(prim.GetAttribute("physics:axis").Get()),
                lower=prim.GetAttribute("physics:lowerLimit").Get(),
                upper=prim.GetAttribute("physics:upperLimit").Get(),
            )
        )
    return joints


def reset_scene() -> None:
    """Empties the Blender scene so each prop is converted in isolation."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_render_geometry(usd_path: Path) -> None:
    """Imports a USD stage's visible render geometry and materials into Blender.

    Args:
        usd_path: the prop's `physx/model.usdc`
    """
    bpy.ops.wm.usd_import(
        filepath=str(usd_path),
        # Collision meshes are tagged purpose="guide"; proxies aren't used by USDCraft.
        import_guide=False,
        import_proxy=False,
        import_render=True,
        import_visible_only=True,
        import_materials=True,
        import_usd_preview=True,
    )


def decimate_heavy_meshes() -> int:
    """Adds a Decimate modifier to every mesh above the triangle cap.

    The glTF exporter applies modifiers, so geometry is reduced only in the
    output file.

    Returns:
        approximate triangle count after decimation: each decimated mesh is
        counted at the cap, which Blender's Decimate hits only approximately
    """
    total = 0
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        tris = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        if tris > MAX_TRIS_PER_MESH:
            mod = obj.modifiers.new(name="decimate", type="DECIMATE")
            mod.ratio = MAX_TRIS_PER_MESH / tris
            tris = MAX_TRIS_PER_MESH
        total += tris
    return total


def scene_size_m() -> list[float]:
    """Returns the prop's bounding box size in metres as [x, y, z] in Blender's Z-up frame."""
    low = mathutils.Vector((float("inf"),) * 3)
    high = mathutils.Vector((float("-inf"),) * 3)
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        # bound_box corners are in object space; move them to world space first.
        for corner in obj.bound_box:
            world = obj.matrix_world @ mathutils.Vector(corner)
            low = mathutils.Vector(map(min, low, world))
            high = mathutils.Vector(map(max, high, world))
    return [round(h - lo, 3) for h, lo in zip(high, low, strict=True)]


def link_names() -> list[str]:
    """Returns the USD link names (direct children of the imported 'Links' node)."""
    links = bpy.data.objects.get("Links")
    return sorted(child.name for child in links.children) if links else []


def export_glb(out_path: Path) -> None:
    """Exports the whole scene as a Y-up glTF binary with modifiers applied.

    Args:
        out_path: destination `.glb`
    """
    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        export_animations=False,
    )


def convert(row: dict[str, str], raw_dir: Path, out_dir: Path) -> PropEntry:
    """Converts one picked prop and returns its manifest entry.

    Args:
        row: one line of picked.csv
        raw_dir: local mirror of the dataset (contains `rigid/...`)
        out_dir: where `.glb` files are written

    Returns:
        the manifest entry for this prop
    """
    usd_path = raw_dir / row["path"] / "physx" / "model.usdc"
    file_name = f"{slugify(row['category'])}.glb"

    reset_scene()
    import_render_geometry(usd_path)
    triangles = decimate_heavy_meshes()
    entry = PropEntry(
        file=file_name,
        category=row["category"],
        source_object_id=row["object_id"],
        source_path=row["path"],
        triangles=triangles,
        size_m=scene_size_m(),
        links=link_names(),
        joints=read_joints(usd_path),
    )
    export_glb(out_dir / file_name)
    return entry


def main(picked_csv: Path, raw_dir: Path, out_dir: Path) -> None:
    """Converts every prop in picked.csv and writes manifest.json next to them.

    One failing prop is reported and skipped so a single bad stage doesn't
    block the rest of the set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[PropEntry] = []
    failures: list[str] = []
    with picked_csv.open() as f:
        for row in csv.DictReader(f):
            try:
                entry = convert(row, raw_dir, out_dir)
            except Exception as exc:  # noqa: BLE001 - report and continue with the rest
                failures.append(f"{row['category']}: {exc}")
                continue
            entries.append(entry)
            print(f"ok {entry['file']} tris={entry['triangles']} joints={len(entry['joints'])}")

    manifest = {
        "source": "https://huggingface.co/datasets/nvidia/USDCraft-10K",
        "license": "Apache-2.0",
        "converted_by": "scripts/convert_usdcraft.py",
        "joint_axis_note": (
            "axis letters are in the USD Z-up frame; in glTF Y-up, USD Z is Y and USD Y is -Z"
        ),
        "props": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"converted {len(entries)}, failed {len(failures)}")
    for line in failures:
        print("FAILED", line)


if __name__ == "__main__":
    # Blender passes its own args first; ours come after the "--" separator.
    args = sys.argv[sys.argv.index("--") + 1 :]
    main(Path(args[0]), Path(args[1]), Path(args[2]))
