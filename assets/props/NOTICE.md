# USDCraft-10K props: attribution

The `.glb` files in this folder are derived from **NVIDIA USDCraft-10K**
(https://huggingface.co/datasets/nvidia/USDCraft-10K), licensed under the
**Apache License 2.0** (https://www.apache.org/licenses/LICENSE-2.0).

**Modifications:** converted from OpenUSD (`physx/model.usdc`) to glTF binary
with `scripts/convert_usdcraft.py`. Collision meshes were removed, meshes over
4,000 triangles were decimated, and the axes were converted from Z-up to Y-up.
Joint data was extracted into `manifest.json`.

`manifest.json` lists the source object ID and dataset path for every file.
