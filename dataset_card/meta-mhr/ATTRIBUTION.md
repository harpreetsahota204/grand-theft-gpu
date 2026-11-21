# meta-mhr: attribution

**What:** Meta's Momentum Human Rig (MHR) body as glTF. It's a parametric human body model
with a skinned mesh on a skeleton, plus identity and expression blendshapes (glTF morph
targets). Seven levels of detail, from `mhr-lod0.glb` (about 141 MB, research detail) to
`mhr-lod6.glb` (about 1.5 MB). LOD 3–6 suit a browser game.

It has no clothes, textures or animations. It's a base body to shape, dress or pose.

**Created by:** Meta, [facebookresearch/MHR](https://github.com/facebookresearch/MHR),
release `v1.0.1` (`assets.zip`).

**License:** Apache License 2.0. The full text is in `LICENSE`.

**What we changed:** converted `assets/lod0.fbx` … `lod6.fbx` to GLB in Blender with
`scripts/convert_mhr.py` in [grand-theft-gpu](https://github.com/harpreetsahota204/grand-theft-gpu),
keeping the skin, skeleton and blendshapes. MHR's neural pose correctives (`.npz`, `.pt`)
aren't included; they need PyTorch and aren't usable in a browser.
