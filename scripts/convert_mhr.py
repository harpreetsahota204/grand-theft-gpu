"""Converts Meta MHR's level-of-detail FBX bodies to glTF binary for the browser.

MHR (Momentum Human Rig, https://github.com/facebookresearch/MHR, Apache 2.0)
ships its parametric body as `assets/lod0.fbx` … `lod6.fbx`: a skinned mesh on
a skeleton with identity and expression blendshapes. three.js can't load FBX
blendshapes reliably, so this runs inside Blender and exports each LOD as a
Y-up `.glb` with skin, skeleton and shape keys (glTF morph targets) intact.

Run (from the repo root):
    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
        --python scripts/convert_mhr.py -- <dir with lod*.fbx> <out dir>
"""

import sys
from pathlib import Path

import bpy  # type: ignore[import-not-found]  # only importable inside Blender


def convert(fbx: Path, out: Path) -> None:
    """Imports one FBX into an empty scene and exports it as .glb.

    Args:
        fbx: an MHR `lodN.fbx`
        out: destination `.glb`
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(fbx))
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        export_yup=True,
        export_skins=True,
        # Shape keys become glTF morph targets: MHR's identity/expression controls.
        export_morph=True,
        export_animations=False,
    )


def main(src_dir: Path, out_dir: Path) -> None:
    """Converts every lod*.fbx in src_dir to out_dir/mhr-lodN.glb.

    Args:
        src_dir: MHR's `assets/` folder holding `lod0.fbx` … `lod6.fbx`
        out_dir: destination folder (created if missing)
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for fbx in sorted(src_dir.glob("lod*.fbx")):
        out = out_dir / f"mhr-{fbx.stem}.glb"
        convert(fbx, out)
        print(f"ok {out.name} {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    # Blender passes its own args first; ours come after the "--" separator.
    args = sys.argv[sys.argv.index("--") + 1 :]
    main(Path(args[0]), Path(args[1]))
