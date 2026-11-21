---
pretty_name: Grand Theft GPU Assets
license: other
license_name: mixed-per-folder
license_link: https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets#licenses-and-credit
tags:
- 3d
- glb
- gltf
- game-assets
- threejs
- characters
- animation
- city
- openstreetmap
- san-francisco
size_categories:
- 1K<n<10K
---

# Grand Theft GPU Assets

The 3D assets for **[Grand Theft GPU](https://github.com/harpreetsahota204/grand-theft-gpu)**,
a browser heist game set in a parody of San Francisco. Two AI models race to build it, each with
$100 of inference. Everything here is ready for three.js: real people with motion-capture clips,
a real slice of San Francisco with its hills, city building kits, props, and the GPU you steal.

**Every folder keeps its own license and an `ATTRIBUTION.md` saying who made it, where it came
from and what we changed.** Most of this is other people's work. Please credit them as their
licenses ask.

## What's inside

| Folder | What | Items | Size | License | Created by |
|---|---|---|---|---|---|
| `rocketbox-avatars/` | Rigged people: business, medical, police, fire, construction, pilots, security, everyday adults. Four tiers: `objects` (web), `lods`, `mobile`, `collision` | 105 people | 524 MB | MIT | Microsoft Rocketbox; web conversion by codepawl |
| `rocketbox-motions/` | Motion-capture clips on the Rocketbox rig: idle, talking, sitting, phone calls, documents, dancing, cheering | 326 clips | 233 MB | MIT | Microsoft Rocketbox; web conversion by codepawl |
| `quaternius-animations/` | Walk, run, sprint, crouch, drive, climb and more on one humanoid rig, plus a mannequin | 89 clips | 15 MB | CC0 | Quaternius |
| `meta-mhr/` | Meta's parametric human body (Momentum Human Rig), 7 LODs with blendshapes | 7 | 211 MB | Apache 2.0 | Meta |
| `sf-city/` | SoMa → FiDi → Embarcadero: terrain with hills, 2,168 buildings at real heights, streets, bay, plus a street graph and building data | 1 scene + data | 16 MB | ODbL (data) / OSM credit (scene) | © OpenStreetMap contributors; USGS 3DEP elevation |
| `kenney/` | Low-poly city kits (commercial, suburban, industrial, roads), retro urban kit, modular buildings, furniture, cars | 714 | 13 MB | CC0 | Kenney; web conversion by codepawl |
| `usdcraft-props/` | Server racks, safes, an ATM, a forklift, a drone, street furniture, with joints for doors and lids | 45 | 9.4 MB | Apache 2.0 | NVIDIA USDCraft-10K; converted by us |
| `gpu/` | The loot: a graphics card with fans and RGB strips you can animate | 1 | 0.9 MB | CC0 | Grab3D |

All models are `.glb` (binary glTF 2.0), in metres, with y up.

## Download

Everything (about 1 GB):

```bash
hf download harpreetsahota/grand-theft-gpu-assets --repo-type dataset --local-dir grand-theft-gpu-assets
```

One folder, or just a few files:

```bash
hf download harpreetsahota/grand-theft-gpu-assets --repo-type dataset \
  --include "sf-city/*" --local-dir assets
hf download harpreetsahota/grand-theft-gpu-assets --repo-type dataset \
  --include "rocketbox-avatars/objects/business-*/*" --local-dir assets
```

From Python:

```python
from huggingface_hub import snapshot_download

path = snapshot_download(
    "harpreetsahota/grand-theft-gpu-assets",
    repo_type="dataset",
    allow_patterns=["kenney/objects/city-kit-*/*", "gpu/*"],
)
```

Pin a revision (`--revision <commit>`) when you need the exact same files every time.

## Using them in three.js

Files in `rocketbox-avatars/objects`, `rocketbox-motions/objects` and `kenney/objects` use
**meshopt** compression:

```js
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);
const person = await loader.loadAsync('rocketbox-avatars/objects/business-female-01/business-female-01.glb');
```

* **People and motions:** each Rocketbox motion file contains an avatar with the clip baked on.
  The clip plays on any Rocketbox person, because they share the same 3ds Max Biped skeleton.
* **Walking:** Rocketbox has no walk or run clips. The Quaternius clips do, on a different rig;
  retarget them with `SkeletonUtils.retargetClip`.
* **The city:** `sf-city/streets.json` is a graph you can route traffic on. `buildings.json`
  gives each building's footprint and height, so you can turn one into a data center.

## Licenses and credit

| Folder | License | Credit line |
|---|---|---|
| `rocketbox-avatars/`, `rocketbox-motions/` | MIT (full text in each folder's `LICENSE`) | Microsoft Rocketbox Avatar Library, © 2020 Microsoft. Cite: Gonzalez-Franco et al., *The Rocketbox Library and the Utility of Freely Available Rigged Avatars*, Frontiers in Virtual Reality, 2020. Web conversion: [codepawl](https://huggingface.co/codepawl) |
| `quaternius-animations/` | CC0 1.0 | Animations by Quaternius (quaternius.com), appreciated but not required |
| `meta-mhr/` | Apache 2.0 | MHR by Meta (facebookresearch/MHR) |
| `sf-city/` | ODbL 1.0 for the data; the scene is a Produced Work | Map data © OpenStreetMap contributors. Elevation: Mapzen / AWS Terrain Tiles, USGS 3DEP |
| `kenney/` | CC0 1.0 | 3D models by Kenney (kenney.nl), appreciated but not required. Web conversion: codepawl |
| `usdcraft-props/` | Apache 2.0 (see `NOTICE.md`) | NVIDIA USDCraft-10K; converted to GLB by grand-theft-gpu |
| `gpu/` | CC0 1.0 | Grab3D, appreciated but not required |

The mirrored folders are pinned copies of [`codepawl/rocketbox-avatars-glb`](https://huggingface.co/datasets/codepawl/rocketbox-avatars-glb),
[`codepawl/rocketbox-motions-glb`](https://huggingface.co/datasets/codepawl/rocketbox-motions-glb) and
[`codepawl/kenney-glb`](https://huggingface.co/datasets/codepawl/kenney-glb). Each folder's
`ATTRIBUTION.md` records the exact revision.

## What we left out, and why

* **No animals or children** among the people. The game only needs regular adults.
* **Four avatars in religious or culturally specific dress were excluded**, so no character in
  a satire with cartoon fighting can be cast as a spy or villain because of how they dress. **Two
  swimwear avatars** were excluded because they don't fit city streets. They remain available
  in the upstream dataset.
* **No real building names** in the city data. The game uses parody names.
* **The base game** that Grand Theft GPU starts from
  ([kartik786-git/gta-clone-threejs](https://github.com/kartik786-git/gta-clone-threejs)) isn't
  included, because it has no license. It's fetched from its author at build time.

## How this was built

Every folder can be rebuilt from its sources with the `buildoff` CLI in
[grand-theft-gpu](https://github.com/harpreetsahota204/grand-theft-gpu):
`buildoff assets mirror` (pinned third-party sets), `buildoff assets city` (OpenStreetMap +
elevation), and `buildoff assets dataset` (attribution files and this card).
