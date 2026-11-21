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
- hdri
- pbr-textures
- audio
- fonts
size_categories:
- 1K<n<10K
---

# Grand Theft GPU Assets

The 3D assets for **[Grand Theft GPU](https://github.com/harpreetsahota204/grand-theft-gpu)**,
a browser heist game set in a parody of San Francisco. Two AI models race to build it, each with
$100 of inference. Everything here is ready for three.js: real people with motion-capture clips,
a real slice of San Francisco with its hills, city building kits, props, and the GPU you steal,
plus the skies, surface textures, trees, sounds, particle sprites and fonts that make it look and
sound like a place.

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
| `vehicles-objaverse/` | Realistic low-poly vehicles: police sedan, taxi, compact cars, sedan, muscle cars, delivery vans, ambulance, fire truck, city bus, mini truck, vintage sedan. Tiers: `objects`, `lods`, `collision` | 13 | 24 MB | CC-BY 4.0 (credit each artist) | Sketchfab artists via Objaverse; web conversion by codepawl |
| `vehicles-quaternius/` | Modern SUV and taxi for traffic and robotaxis | 2 | 0.7 MB | CC0 | Quaternius; web conversion by codepawl |
| `kenney/` | Low-poly city kits (commercial, suburban, industrial, roads), retro urban kit, modular buildings, furniture | 664 | 13 MB | CC0 | Kenney; web conversion by codepawl |
| `usdcraft-props/` | Server racks, safes, an ATM, a forklift, a drone, street furniture, with joints for doors and lids | 45 | 9.4 MB | Apache 2.0 | NVIDIA USDCraft-10K; converted by us |
| `gpu/` | The loot: a graphics card with fans and RGB strips you can animate | 1 | 0.9 MB | CC0 | Grab3D |
| `trees-google-poly/` | Street trees (elm, sycamore, oak) and palms (queen, royal, date, plain, potted lady palm). Normalised to about 1 m tall; scale up | 8 | 1.7 MB | CC-BY 3.0 (credit each artist) | Google Poly artists; web conversion by codepawl |
| `polyhaven-hdris/` | Sky and lighting HDRIs: midday, SF fog, golden hour, sunset, dusk, clear night, city-glow night, Golden Gate hills. `_1k.hdr` and `_2k.hdr` | 8 | 48 MB | CC0 | Poly Haven |
| `polyhaven-textures/` | PBR surfaces at 1k (color, normal_gl, roughness, ao): asphalt, pavers, concrete, plaster, brick, grass, roof tiles, metal, floors | 16 | 35 MB | CC0 | Poly Haven |
| `ambientcg-textures/` | PBR at 1k: office facades in day/night pairs (night ones have emission maps for lit windows), glass towers, roads with lane markings, asphalt | 20 | 67 MB | CC0 | ambientCG |
| `audio-opengameart/` | Engine start, engine loops idle → high revs, tire squeal, alarm, siren, city ambience, footsteps on 6 surfaces | 7 sets | 2.9 MB | CC0 and CC-BY 3.0 (per item) | OpenGameArt artists |
| `kenney-media/` | Impact sounds (punches, glass, metal, wood), interface sounds, and transparent particle sprites (smoke, fire, sparks, muzzle flashes) | 3 packs | 7.7 MB | CC0 | Kenney |
| `google-fonts/` | HUD and title fonts: Bebas Neue, Anton, Rajdhani, Share Tech Mono | 4 | 1.4 MB | OFL 1.1 | Their designers, via Google Fonts |

All models are `.glb` (binary glTF 2.0), in metres, with y up. Every item in the six media
folders (skies, textures, sounds, sprites, fonts) has an `info.json` with what it is, who made it,
its licence, a sha256 per file and, for textures, the real-world size one image covers (`size_m`).

## Download

Everything (about 1.2 GB):

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

Files in the `objects/` folders of `rocketbox-avatars`, `rocketbox-motions`, `kenney`,
`vehicles-objaverse`, `vehicles-quaternius` and `trees-google-poly` use **meshopt** compression:

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
  `sf-city.glb` is split into layers (`walls_<type>`, `roofs_<type>`, `roads`, `terrain`, `water`)
  with named materials and **UVs in metres**, so a texture covering `size_m` metres tiles with
  `texture.repeat.set(1 / size_m[0], 1 / size_m[1])`. `meta.json` documents the convention.
* **Skies:** load an `.hdr` with `RGBELoader`, run it through `PMREMGenerator`, and set it as
  `scene.environment` (lighting) and `scene.background`.
* **Textures:** `normal_gl` / `NormalGL` maps use the OpenGL convention three.js expects. Night
  facades come with an `Emission` map: use it as `emissiveMap` for lit windows.

## Licenses and credit

| Folder | License | Credit line |
|---|---|---|
| `rocketbox-avatars/`, `rocketbox-motions/` | MIT (full text in each folder's `LICENSE`) | Microsoft Rocketbox Avatar Library, © 2020 Microsoft. Cite: Gonzalez-Franco et al., *The Rocketbox Library and the Utility of Freely Available Rigged Avatars*, Frontiers in Virtual Reality, 2020. Web conversion: [codepawl](https://huggingface.co/codepawl) |
| `quaternius-animations/` | CC0 1.0 | Animations by Quaternius (quaternius.com), appreciated but not required |
| `meta-mhr/` | Apache 2.0 | MHR by Meta (facebookresearch/MHR) |
| `sf-city/` | ODbL 1.0 for the data; the scene is a Produced Work | Map data © OpenStreetMap contributors. Elevation: Mapzen / AWS Terrain Tiles, USGS 3DEP |
| `vehicles-objaverse/` | CC-BY 4.0 (full text in `LICENSE`) | **Credit each model's artist**; the table in `vehicles-objaverse/ATTRIBUTION.md` lists every title, artist and original Sketchfab link. Via [Objaverse](https://objaverse.allenai.org/); web conversion: codepawl |
| `vehicles-quaternius/` | CC0 1.0 | Models by Quaternius (quaternius.com), appreciated but not required. Web conversion: codepawl |
| `kenney/` | CC0 1.0 | 3D models by Kenney (kenney.nl), appreciated but not required. Web conversion: codepawl |
| `usdcraft-props/` | Apache 2.0 (see `NOTICE.md`) | NVIDIA USDCraft-10K; converted to GLB by grand-theft-gpu |
| `gpu/` | CC0 1.0 | Grab3D, appreciated but not required |
| `trees-google-poly/` | CC-BY 3.0 | **Credit each model's artist**; see the table in `trees-google-poly/ATTRIBUTION.md`. Via Google Poly; web conversion: codepawl |
| `polyhaven-hdris/`, `polyhaven-textures/` | CC0 1.0 | Poly Haven (polyhaven.com), appreciated but not required |
| `ambientcg-textures/` | CC0 1.0 | ambientCG (ambientcg.com), appreciated but not required |
| `audio-opengameart/` | CC0 1.0 or CC-BY 3.0, per item | **Credit the CC-BY items** (tire squeal: qubodup; siren: FiveBrosStopMosYT; footsteps: congusbongus and the Freesound recordists in each `license.txt`). Full table in `ATTRIBUTION.md` |
| `kenney-media/` | CC0 1.0 | Kenney (kenney.nl), appreciated but not required |
| `google-fonts/` | SIL Open Font License 1.1 (`OFL.txt` next to each font) | Each font's copyright line is in its `OFL.txt` |

The mirrored folders are pinned copies of [`codepawl/rocketbox-avatars-glb`](https://huggingface.co/datasets/codepawl/rocketbox-avatars-glb),
[`codepawl/rocketbox-motions-glb`](https://huggingface.co/datasets/codepawl/rocketbox-motions-glb) and
[`codepawl/kenney-glb`](https://huggingface.co/datasets/codepawl/kenney-glb),
[`codepawl/objaverse-clean-glb`](https://huggingface.co/datasets/codepawl/objaverse-clean-glb),
[`codepawl/quaternius-glb`](https://huggingface.co/datasets/codepawl/quaternius-glb) and
[`codepawl/google-poly-glb`](https://huggingface.co/datasets/codepawl/google-poly-glb). Each folder's
`ATTRIBUTION.md` records the exact revision.

## What we left out, and why

* **No animals or children** among the people. The game only needs regular adults.
* **Four avatars in religious or culturally specific dress were excluded**, so no character in
  a satire with cartoon fighting can be cast as a spy or villain because of how they dress. **Two
  swimwear avatars** were excluded because they don't fit city streets. They remain available
  in the upstream dataset.
* **No real building names** in the city data. The game uses parody names.
* **No Kenney car kit.** Its toy-like style clashed with the realistic people and the real city,
  so it was replaced by the vehicle folders above. Some original vehicle titles name a real
  manufacturer; the models themselves carry no brand logos, and the game catalog uses generic
  names ("police sedan", "city bus").
* **The base game** that Grand Theft GPU starts from
  ([kartik786-git/gta-clone-threejs](https://github.com/kartik786-git/gta-clone-threejs)) isn't
  included, because it has no license. It's fetched from its author at build time.

## How this was built

Every folder can be rebuilt from its sources with the `buildoff` CLI in
[grand-theft-gpu](https://github.com/harpreetsahota204/grand-theft-gpu):
`buildoff assets mirror` (pinned third-party sets), `buildoff assets city` (OpenStreetMap +
elevation), `buildoff assets textures` (Poly Haven and ambientCG, md5-checked where the source
publishes one), `buildoff assets media` (sounds, sprites, fonts), and `buildoff assets dataset`
(attribution files and this card).
