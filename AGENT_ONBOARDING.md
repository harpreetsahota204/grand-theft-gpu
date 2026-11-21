# Agent onboarding

Read this first. It tells an agent where the project stands, what has been decided and why, and what bit us along the way. `README.md` covers how to run things; this file covers context.

**Keep it current.** When a decision is made, a phase finishes, or something surprising turns up, update the matching section in the same change. Delete anything that stops being true.

_Last updated: 2026-11-20_

---

## 1. The project in one paragraph

This is a DevRel piece for Fireworks. Kimi K3.1 Pro (an open model on Fireworks) and Claude Opus 5.5 each get $100 of inference and the same spec, and each builds a browser GTA-style game in Claude Code. Results are scored on a four-tier heist ladder (Small-time → Kingpin, labeled GTA 1→4 in the video) and cut into a split-screen race video. Part 2 (later) trains Kimi with RL to play its own game. Nexus, the Fireworks tool that routes Claude Code to Fireworks models, is the plumbing: routing, refereeing spend, and telemetry. It is the tool in the story, never the topic. The internal program brief is `PROGRAM_BRIEF.md`; it stays local and is gitignored, so never commit it.

## 1b. The game: Grand Theft GPU (GT-GPU)

Decided 2026-11-20. Both models get the same framing and the same starting assets. Past that framing they choose freely; we stay hands-off.

**Locked in the prompt (frame + cast):**
- Title: **Grand Theft GPU**. Setting: **San Silicon**, a parody of San Francisco (decided 2026-11-20: parody names for the city, landmarks and neighborhoods; consistent with the no-real-brands rule). Core goal: **steal GPUs**.
- Cast: **archetypes, never real people.** The kind of characters you'd find in a Twitter/X thread: VCs, hype beasts, grifters, anon accounts. They talk like the posts.
- Brands: **archetypes too.** A "robotaxi with the spinning roof sensor," never "Waymo." No real company names, logos or people.
- The plot, missions, dialogue and characters' details are **the models' to write.**

**Starting code and assets (identical for both models):**
- **Base game:** https://github.com/kartik786-git/gta-clone-threejs. A third-person, on-foot three.js game (walk, sprint, jump, melee, enemies) with `city.glb` and FBX characters. All the code is in `src/main.js`, about 1.3K lines. **No cars.** It has no license file; the user's call is to give attribution and build on it.
  - **Decided: fetch it at seed time, pinned to commit `babb6232df0f50d92e66a4b994a5fbc14fcc37d9`** (2026-06-16). It is *not* vendored or added as a submodule, so nothing is re-hosted, our repo stays small, and the link doubles as attribution. When seeding a workspace: clone at that commit, drop the duplicate top-level `assets/` (the game loads from `public/assets/`), and copy in our `assets/`. The base is 71 MB, because `city.glb` alone is 90 MB per copy and every asset appears twice. It builds with Vite 8 and three 0.184 (`npm install`, `npm run build`).
- **Props:** NVIDIA **USDCraft-10K** (Apache 2.0). **Done: 45 props** in `assets/props/*.glb`, 9.4 MB, all rendered and checked on a contact sheet. We took variant `01_` of each curated category. `assets/props/manifest.json` lists each prop's file, source object ID, triangle count, size in metres, links (movable parts) and **joints** (154 in total: revolute/prismatic, with parent/child link, axis and limits). The joint axes are in the USD Z-up frame; the manifest explains the mapping to Y-up. Converter: `scripts/convert_usdcraft.py`, run in Blender (details in the README).
  - **The props:** heist targets (rack-mount server, server rack cabinet, desktop tower, laptop, monitor, home safe, room safe, safe deposit box cabinet, ATM, battery rack, wi-fi router); heist tools (forklift, pallet jack, hand truck, platform truck, pallet, pallet rack, parcel box, quadcopter drone, autonomous mobile robot, industrial workbench, computer desk); city streets (traffic light, traffic cone, traffic barrier, jersey barrier, street lamp, street sign post, bus stop sign, parking meter, fire hydrant, bike share dock, bicycle, electric scooter, kick scooter, EV charging station, vending machine, turnstile, boom/flap barrier gates, park bench, public trash can, street mailbox, anti-theft security gate, signal tower light).
  - Every mesh is decimated to at most 4K tris (`MAX_TRIS_PER_MESH`), because some source parts had 65K. Collision meshes (USD purpose `guide`) are dropped.
- **Cars:** **Kenney Car Kit 3.1, CC0**, in `assets/cars/`. That's 49 GLBs plus `License.txt` and `Preview.png`, 5.6 MB in total. They include sedan, sedan-sports, hatchback-sports, suv, suv-luxury, taxi, police, ambulance, firetruck, van, delivery, truck, garbage-truck, tractors, race cars, karts, cones, a box, and **debris parts** (doors, bumper, tire, plates), which are useful for damage. **Wheels are separate nodes** (`wheel-front-left`, …) and can spin and steer. All GLBs share one texture at `Textures/colormap.png`, which must sit next to them. There's no robotaxi model; the models can add the roof sensor to a sedan or SUV. USDCraft has no full-size cars, which is why we use this kit.
  - The download link sits behind a donation popup. To get it with a script: load the asset page with a cookie jar, then `GET https://kenney.nl/download-link/<hex id>` returns a signed `url`.
- **The GPU (the loot):** USDCraft has no graphics card, so we supply one, the same for both models: `assets/gpu/graphics-card-light.glb` from [Grab3D](https://grab3d.com/models/electronics/graphics-card/). It's **CC0**, made procedurally, 12.6K tris, 891 KB. A render confirmed **no brand logos**. It has 11 named meshes: `_body`, `_fins`, `_fan_N_rotor_M` (spinnable) and `_light_strip_rgb_N` (pulsable). The style is pastel; models can recolor it. Grab3D's CC0 [Cozy PC Parts kit](https://grab3d.com/kits/cozy-pc-parts/) has matching extra loot (PSU, motherboard, network switch, gaming PC) if we want more.
- **No URDFs needed.** URDF is for robot sims; the game needs `.glb` meshes plus simple collision boxes. USDCraft joints survive conversion as separate mesh pieces (rack doors, safe doors) that the game can animate. Part 2 RL doesn't need URDF either, because the game itself is the environment.

**Asset sources, revised 2026-11-20 after searching Hugging Face.** The user wants *regular people only*, no creatures. The HF publisher **codepawl** has already converted most of what we planned into web-ready glTF (meshopt + WebP, with LOD and mobile tiers):
- People: [`codepawl/rocketbox-avatars-glb`](https://huggingface.co/datasets/codepawl/rocketbox-avatars-glb) (MIT). **105 people**: adults and professions only. No animals, no children, and (the user's call, 2026-11-20) **no religious or culturally specific dress** (`female-adult-10/16`, `male-adult-19/21`), so no model can cast them as spies or enemies, and **no swimwear** (`sports-female-01`, `sports-male-01`). The exclusions live in `scripts/mirror_sources.json` (`exclude_items`). All 105 were verified on a rendered contact sheet. Note: codepawl files use **meshopt**, so three.js needs `loader.setMeshoptDecoder(MeshoptDecoder)`.
- Motions: [`codepawl/rocketbox-motions-glb`](https://huggingface.co/datasets/codepawl/rocketbox-motions-glb) (MIT), 326 clips on the Rocketbox rig (talk, idle, sit, phone, dance…). It has **no walk or run clips**, so we're also adding the **Quaternius Universal Animation Library 1+2** (CC0, 89 clips incl. walk, run, drive; a different rig, so models must retarget).
- **Vehicles (2026-11-21):** the user found Kenney's car kit toy-like ("cocomelon") next to realistic people and real SF, so it was **removed**. It's replaced by **13 hand-picked Objaverse vehicles** (`vehicles-objaverse/`, CC-BY 4.0: police sedan, taxi, compact car/van, sedan, two muscle cars, delivery van, ambulance, fire truck, city bus, mini truck, vintage sedan) plus **Quaternius SUV + taxi** (`vehicles-quaternius/`, CC0). CC-BY means **every artist is credited** in the generated table in `vehicles-objaverse/ATTRIBUTION.md`. Four upstream folders had real brand names (Carbon Motors, Isuzu, GAZ) and are renamed via `rename_items` in `scripts/mirror_sources.json` (e.g. `police-sedan-692c68c4`); the catalog uses generic names (`VEHICLE_NAMES`) and keeps file-id words out of vehicle tags. Brands were rejected from the picks too (a Hot Wheels livery, a VW badge).
- City pieces: [`codepawl/kenney-glb`](https://huggingface.co/datasets/codepawl/kenney-glb) (CC0, 46 packs incl. City Kits, Retro Urban, Modular Buildings). The **real SF slice (OSM + USGS) is still ours to build**; nobody has one.
- On demand: [`codepawl/asset-index`](https://huggingface.co/datasets/codepawl/asset-index), 37,668 assets with real sizes. Racing models may search its **CC0 rows only** and fetch extras mid-race. Megascans rows are excluded (Fab license, no redistribution).
- **Hosting: mirror everything into `harpreetsahota/grand-theft-gpu-assets`** (the user's call), with a per-source folder, license file and attribution crediting both the original creators and codepawl's conversions. The base game is still excluded (no license).
- The Quaternius *Universal Base Characters* are only on itch.io, and scripted download failed (itch rejects the key). They're not in codepawl's mirror either, so they're skipped unless the user downloads them manually.

**Asset expansion (decided 2026-11-20, after the $5 test run).** The test showed the models *do* use the assets we give them (both loaded cars and props dynamically), but we gave them no people, so every NPC was built from boxes. The city (base `city.glb`) also doesn't look like SF. Adding:
- **People:** Quaternius Universal Base Characters + Universal Animation Library (CC0, glTF, one shared rig); **all ~115 Microsoft Rocketbox avatars** (MIT, FBX → glb); Meta **MHR** base body (Apache 2.0). Meta's Sapiens/Sapiens2 are human *vision* models, not avatars, so they're not usable as assets.
- **City:** a **real SF slice, SoMa → FiDi → Embarcadero (~2 km²)**, from OpenStreetMap streets and buildings (ODbL, attribution required) plus USGS elevation for hills (public domain), converted to .glb plus a JSON street graph. Also **Kenney City Kits** (Commercial, Suburban, Roads, Industrial; CC0). The base `city.glb` stays as an option.
- **This means `prompt-v2`:** the asset section of the prompt changes. The `test-5usd-001` run becomes a dry run on prompt-v1.

**Must-haves (the prompt requires all four):** steal a GPU · drive a car (enter, drive, exit) · talk to an archetype NPC in their voice · get chased (a pursuer with a heat/wanted mechanic).

**Inspiration list (in the prompt as "the world this lives in, use what you like"; not required):** raising money from VCs · poaching top engineers and researchers · honeypot spies after your secrets (framing left to the models; the off-limits rules still apply) · AI doomer vs. "boomer" debates · funny billboards and ads for AI insurance and other absurd AI companies · general Silicon Valley tropes. Whatever a model picks up shows as depth within the tiers.

**Off limits:** no real people or brands · no slurs and no punching down (the satire targets tech-culture archetypes) · no realistic real-world theft or hacking how-tos in any text · cartoonish violence only (clip-safe for a company account). Dunking on the other model or its lab is *not* banned.

**Scoring: a heist ladder** that replaces the GTA 1–4 ladder. The "GTA 1→4" labels stay for the video. The base repo is 3D already, so top-down tiers make no sense.

| Tier | Label | Unlocks when |
|---|---|---|
| T1 | "GTA 1" | You can steal a GPU |
| T2 | "GTA 2" | You escape by car while being chased (heat/wanted) |
| T3 | "GTA 3" | A multi-mission story with talking archetypes |
| T4 | "GTA 4" | A living San Silicon: traffic, robotaxis, day/night |

The exact pass/fail checks per tier still need writing and locking with the prompt.

## 2. How to work with the user

The user is the architect and decision-maker. The agent writes the code and runs the commands. The maintainer's private working-style notes are in `CLAUDE.local.md`. It's gitignored, but Claude Code loads it automatically when it's present.

- **Code standards:** Google-style docstrings and full type hints on every function, "why" comments, and the cleanup checklist run twice. `ruff` is configured in `pyproject.toml`.
- **Git:** commit only when asked. The repo is **public**: scan for secrets, personal info and internal links (Notion, Slack, claude.ai) before every push.

## 3. Status

| Phase | State |
|---|---|
| Race infrastructure (`harness/`) | ✅ Built, tested end to end, committed |
| Game direction (Grand Theft GPU, see 1b) | ✅ Framing, must-haves, limits and tier shape decided |
| GPU asset | ✅ `assets/gpu/` (CC0, verified to have no logos) |
| Car pack (CC0) | ✅ `assets/cars/` (Kenney Car Kit 3.1) |
| USDCraft props → .glb | ✅ `assets/props/` (45 props + manifest), `scripts/convert_usdcraft.py` |
| Replication setup (anyone can rebuild assets and run a race) | ✅ `.python-version`, `uv sync` (all groups by default), `buildoff doctor`, `buildoff assets` (`harness/doctor.py`, `harness/assets.py`). Rebuilt from source and **byte-identical** to `assets/` |
| Public repo | ✅ https://github.com/harpreetsahota204/grand-theft-gpu (public since 2026-11-20). BSL 1.1: non-commercial use granted; converts to Apache 2.0 on 2040-01-22 (4,811 days, the GTA V → GTA 6 wait) or on each version's 4th anniversary if sooner. Before pushing: a secrets/personal-info scan of files and history, and a fresh-clone smoke test. |
| Decide what goes in git | ✅ `assets/` committed (16 MB; licenses allow it). Base game fetched, not vendored. `PROGRAM_BRIEF.md` and `CLAUDE.local.md` gitignored. |
| Game prompt (`prompts/game_spec.md`, `run_rules.md`, `nudge.md`) | 🔒 **Current: `prompt-v4`**, locked 2026-11-21 (user approved the draft as written). v4 = v3 plus: run_rules gains a `tools/screenshot` bullet; the asset list adds trees, skies, textures, sound, effects and fonts; the SF bullet notes UVs in metres; Look and feel says "simple textures, real skies and lighting" and adds sound to the HUD/juice line; meshopt note includes trees. sha256: game_spec `848f2088…fb88`, run_rules `47f85a99…bf80`, nudge `e9cd6279…1902` (unchanged). No race ever ran on v3. Previously `prompt-v3`, locked 2026-11-21. v3 = v2 plus a **Vehicles** bullet (15 realistic vehicles), with the city kits no longer listing cars and the meshopt note covering vehicles. v2 (2026-11-20) introduced the asset tool, people, motions and the real SF map. sha256: game_spec `f8128cb1…19ff`, run_rules `e32a44a0…`, nudge `e9cd6279…`. v1/v2 are superseded; `test-5usd-001` was a dry run on v1. |
| Harness seeding + per-turn Vite build + gameplay screenshots | ✅ `harness/seed.py`, `snapshot.build`. The smoke test on the seeded base (`smoke-seed-002`) passed for both models: turn 0 builds, both added the GPU from our assets, and the screenshots show gameplay. |
| Aesthetics pass (decided 2026-11-21) | 🔄 **A done:** `tools/screenshot` (`harness/shot_tool.py`) is written into every workspace. It builds and renders through the harness's own path in about 20 s, with `--hold KEY:MS` to move first, and prints a JSON result; shots are gitignored. **B done:** `sf-city.glb` layers are now separate meshes with **named PBR materials and metre UVs**: `walls_<type>` (u along the wall, v height above base), `roofs_<type>`, `roads` (u across, v along), `terrain` and `water` (planar). The convention is in `meta.json` (`uv`, `layers`) and the catalog. Verified with test window and lane textures. **Fixed a shipped bug: road triangles faced down** (invisible under single-sided materials; now 0% face down, checked per layer). **C done:** `buildoff assets textures` (`harness/textures.py`, list in `scripts/texture_sources.json`) stages **8 Poly Haven HDRIs** (1k + 2k: midday, SF fog, golden hour, sunset, dusk, clear night, city-glow night, Golden Gate hills), **16 Poly Haven PBR textures** (asphalt, pavers, concrete, plaster, brick, grass, roof tiles, metal, floors), and **20 ambientCG materials** (day/night facade families 018/019/020 with Emission maps for lit windows, glass towers, roads with lane markings), all CC0. Each item has an `info.json` with real-world size in metres, map files and sha256; Poly Haven md5s are verified. Verified by rendering textured SF day and night. **D done:** `trees-google-poly` mirror source (8 CC-BY-3.0 Google Poly trees: elm, sycamore, oak street trees; queen, royal, date and plain palms; a potted lady palm). `buildoff assets media` (`harness/media.py`, list in `scripts/media_sources.json`) stages **OpenGameArt sounds** in `audio-opengameart/` (engine start, 6 engine loops idle→high revs, tire squeal, alarm, siren, city ambience, footsteps on 6 surfaces; CC0 except squeal/siren/footsteps, which are CC-BY-3.0 and credited), **Kenney impact-sounds, interface-sounds and particle-pack** in `kenney-media/` (CC0), and **4 OFL fonts** in `google-fonts/` (Bebas Neue, Anton, Rajdhani, Share Tech Mono) at a pinned google/fonts commit. Each item has an info.json with sha256s; each folder gets a LICENSE.md and an ATTRIBUTION.md **generated from the same plan**, so credits can't drift. Kenney downloads now share `assets.kenney_zip(slug)` (the download id is just hex of `assets/<slug>`). No CC0 police siren, car crash or traffic ambience found on OGA; the impact pack covers crashes. **E in progress:** the catalog now indexes everything (1,294 assets; new categories `sky`, `texture`, `nature`, `sound`, `vfx`, `font`; new fields `maps`, `tile_m`, `files`, `notes`; Kenney sounds/sprites grouped into numbered-variant families with ids like `kenney-media/impact-sounds/impactGlass_heavy`). `fetch`/`tools/assets.mjs` also pull a record's `files` and `maps`; `--tiers` adds 2k skies. CORE_PATTERNS seed trees, 1k skies, all textures, sounds, sprites and fonts (~+125 MB). Media folders' LICENSE.md and ATTRIBUTION.md are generated by `buildoff assets dataset` from each item's info.json (`dataset.media_docs`). The dataset card lists every new folder with credit lines. Gotcha: the Google Poly trees are **normalised to ~1 m tall** (catalog `notes` says so). **Watch/play commands (2026-11-21):** `buildoff status [race-id]` (JSON progress per contender incl. Nexus session and `nexus_meter` command) and `buildoff play <kimi|opus>` (serves `workspace/dist` via `snapshot.AssetServer`, a ThreadingHTTPServer with backlog 256). HUMANS.md gained "How does Nexus put Kimi inside Claude Code?", "Step 5: Watch it run" and "Step 6: Play the builds" (the user wants HUMANS.md to teach Nexus and be the blog's start). **Known harness bug, fix pending until the $25 run ends:** `snapshot.screenshot` still uses the stdlib backlog of 5, so asset-heavy games get `ERR_CONNECTION_RESET` console errors and are wrongly marked not playable (Opus turn 1 in `v4-25usd-001`: 11–20 errors at backlog 5, 0 at 256). Switch it to `AssetServer`, then re-score both builds. **Gap pass (2026-11-21, after E):** (1) **Objaverse vehicles and Google Poly trees were normalised to ~1 m by the upstream converter, and vehicles faced mixed directions.** `dataset.real_size` now sets real size by wrapping each glb scene in one transform node (JSON-only edit, BIN chunk untouched, idempotent via the `gt-gpu-real-size` node). Plan in `mirror_sources.json` `real_size` (`measure`, `items`, `reverse`). Vehicles: length along z, front at +z (verified on profile renders; bus, fire truck and vintage sedan needed `reverse`), wheels on y = 0, centred. Trees: real heights. `catalog.json_bounds` measures bounds from accessor min/max, so it works on meshopt files; catalog `size_m` and vehicle `parts` (wheel meshes) come from it. (2) **`audio-freesound/`**: 8 CC0 sounds (police and ambulance sirens, two crashes, 8.6 min of downtown traffic, horn, handbrake skid, passing car) as Freesound HQ preview MP3s, because originals need OAuth. (3) The user said **not to worry about real brand names on asset textures** (the city bus livery names a real company). Catalog: 1,302 assets. Republished with the user's OK as revision `717f91bbc3755ac942fd0afbbbc657826be126cc` (pinned); a fresh seed (654 MB) had every seeded URL, real-size fire truck (9.5 m) and royal palm (15 m), and the base game built and loaded. **E done (2026-11-21):** published with the user's OK as revision `00367a7c63d4a21fc0c6ae7595ffa18eed44caae` (pinned in `HF_ASSETS_REVISION`; also ships the UV-mapped sf-city with the road fix). A fresh `buildoff fetch --core` pulled 1,849 files (651 MB) and every seeded catalog URL resolved. prompt-v4 locked. **Next:** $5 dry run on prompt-v4 (needs the user's OK).  The user chose all of: (1) a **screenshot tool** so models can see their own game; (2+4) **HDRI skies + PBR textures** (Poly Haven / ambientCG, CC0); (3) **UV-mapped SF buildings and roads** so textures apply; (5–7) **sound, trees, VFX sprites and a HUD font** (CC0/OFL). Vision check passed: **both Kimi K3.1 Pro (via Nexus) and Opus read an image** through Claude Code's Read tool and described it correctly, so the screenshot tool is fair. All of this means a `prompt-v4`. |
| Scoring checklist (pass/fail checks per tier, for judges) | ⬜ The tiers are in the prompt; the detailed checks are still to write |
| $5 dry run on prompt-v1 (`test-5usd-001`) | ✅ Kimi **declared done at $3.75**; Opus **hit the $5 budget** ($5.02). Both took 1 turn, both playable on turn 1, no leaks. Kimi wrote 3 story missions, cars, police, heat, a minimap and parody landmarks. It surfaced 3 harness bugs (below, all fixed) and the missing-people gap (see asset expansion). |
| Stall timeout + stray-server cleanup | ✅ `STALL_TIMEOUT_S` = 600 s with no output and no spend means `stalled` and a nudge. After every turn, processes whose cwd is in the workspace are killed. |
| Asset inventory CLI | ✅ `buildoff inventory` plus `assets/catalog.json` (96 assets, deterministic). |
| Asset mirror staged locally (step 1) | ✅ `~/grand-theft-gpu-assets/`: rocketbox-avatars (105 people, 4 tiers), rocketbox-motions (326 clips), kenney (714 pieces), quaternius-animations (89 clips + mannequin), meta-mhr (7 LOD glbs via `scripts/convert_mhr.py`). Built by `buildoff assets mirror` from the pinned plan in `scripts/mirror_sources.json`. |
| SF city slice (step 2) | ✅ `buildoff assets city` (`harness/sfcity.py`) writes `~/grand-theft-gpu-assets/sf-city/`: `sf-city.glb` (9 MB: terrain with hills, 2,168 buildings at real heights, draped streets, bay water), `buildings.json` (footprints, heights, types; **no names**), `streets.json` (1,809 intersections, 2,179 segments with name, class, lanes, one-way, length), and `meta.json` (ODbL + USGS/Terrain Tiles attribution). Area: SoMa → FiDi → Embarcadero, bbox 37.776–37.797 N, 122.408–122.390 W. The raw OSM snapshot is cached in `_cache/osm.json` (pin it in the dataset; OSM changes over time). Verified on aerial renders. Gotchas: glTF needs NORMALs or three.js renders black; drop zero-area faces (NaN normals stop loading); clip ways to the bbox. |
| Hugging Face dataset (step 3) | ✅ **Live and public:** https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets, revision `4fa7f2681169f2bcf670a4f577e6faabcf63d4cf` (vehicles swap; earlier: `a71295a` Infinity fix, `ec21b08` first upload). 1,769 files (8 folders), about 1 GB, each folder with `LICENSE` + `ATTRIBUTION.md`. Built by `buildoff assets dataset` (cards from the repo's `dataset_card/`) and uploaded by `buildoff assets publish` (`HfApi.upload_folder`; `upload_large_folder` doesn't exist in huggingface_hub 2.x). The round-trip download was byte-identical. Note: `hf download --include` takes one pattern per flag. |
| On-demand `buildoff assets fetch` + move `assets/` off GitHub (step 4) | ✅ **Built 2026-11-20:** catalog v2 (1,202 assets over the whole dataset, pinned to `HF_ASSETS_REVISION`), `buildoff fetch`, seeding from the HF cache (`harness.fetch.CORE_PATTERNS`, 1,220 files, 513 MB, copied in about 1 s), `tools/assets.mjs` in every workspace (Node, zero deps; ranking matches `buildoff inventory`), and `assets/` untracked from git (only `assets/catalog.json` is kept). **Decided: seed the full web tier (~508 MB) into every workspace.** That's GPU, props, all Kenney, SF city, Quaternius, all 105 people (`objects/`) and all 326 motions (`objects/`). **On demand (optional extras):** people's `lods/`, `mobile/`, `collision/` tiers and the MHR bodies. Reasoning: size costs seconds of harness build time and disk, not money or fairness; identical full toolboxes keep the comparison about what each model builds. Stripping meshes from motions would save only ~half (the mocap data itself is heavy) and add a lossy step. | **Decided 2026-11-20:** dataset at `harpreetsahota/grand-theft-gpu-assets`, with one folder per source, each with its own license and attribution files, plus a top-level card. The **GitHub repo goes code-only**: `assets/` is removed from git, and `catalog.json` stays, pinned to an HF revision. `buildoff assets fetch` downloads. **Racing models: a pre-seeded core plus on-demand fetch mid-race** (the user's call; a model that fetches more spends more on it, which is part of what's measured). The base game is **not** uploaded (no license). |
| Full $100 race | ⬜ |
| Scoring commits against the checklist | ⬜ |
| Rendering the race video from logs | ⬜ |
| Part 2: RL environment + training on Fireworks | ⬜ Separate project, after launch |

**Open items:**
- **Anthropic API key (deferred by the user).** The Opus side currently bills through the user's Claude login. A true "$100 at list price" claim needs an API key configured for Nexus.
- Who scores the tiers, and how (the user, a script, or blind testers). Parked.
- The headline depends on the results; the exec sponsor signs off once they're in.

## 4. Decisions and why

| Decision | Why |
|---|---|
| Runs on the user's Mac, both contenders **in parallel** | Same time window and API conditions for both. One race, one dataset. |
| **Nexus is the source of truth for spend** (`nexus claude usage --json`) | Claude Code doesn't recognize `kimi-latest` and priced a call at **2x list** ($0.060 vs. $0.030). Nexus prices at list rates with the source cited and includes subagents. `--max-budget-usd` is therefore useless for Kimi. |
| Nexus **model auto-picking is off**; Kimi is pinned to `kimi-latest` (resolves to `kimi-k3p1-pro`) | The model has to be the only variable. |
| Hard kill at $100, polled every 15 s | Expect a small overshoot. Tests overshot by $0.01–0.05; at $100 it's bounded by about 15 s of spend. |
| **Max 3 nudges**, then the run ends | Keeps "the model called it done" meaningful. "Done" = the model creates `DONE.md`. |
| Tools: Bash, Read, Edit, Write, WebFetch, WebSearch, **Agent** | Subagents were allowed only after a leak test passed (below). |
| Subagents pinned **per process** via `CLAUDE_CODE_SUBAGENT_MODEL` | The Nexus `--subagent` pin is global, so it would send Opus's subagents to Kimi. The per-process env var was tested: each side's subagents stayed on its own model. The watchdog also fails a run if any foreign model appears. |
| Isolation: `--strict-mcp-config` + empty MCP config, `--disable-slash-commands`, workspaces in `~/gta-race-runs/` | Keeps the user's connectors (Notion, Gmail…), skills and project files out of the race. Verified in the session's init event: `mcp_servers: []`, `slash_commands: []`. |
| **No screen recording**; transcripts are timestamped instead | ffmpeg recorded whatever was on top of the screen (the user's Notion and an OS dialog). The video will be rendered from the logs later. Each log line is `{"t": seconds, "event": ...}`. |
| Unpriced Nexus rows → **warning only** (`events.jsonl`) | The user's call. Never seen in testing. |
| Same harness, same flags; only `--model` differs | Fairness, and it's the claim the video makes. |

## 5. Gotchas we hit (save yourself the time)

- **`claude --bare` breaks Nexus routing** ("Not logged in"). It skips the settings that carry the Fireworks auth. Use the explicit isolation flags instead.
- **Don't read `~/.claude/settings.json`.** It holds credentials, and the permission classifier blocks it. Use `nexus claude status` instead.
- **`--dangerously-skip-permissions` is blocked by the classifier.** The harness uses `--permission-mode acceptEdits` plus `--allowed-tools` instead.
- **The shell is zsh.** `$FLAGS` doesn't word-split. Put multi-flag commands in a bash script with arrays.
- **`--resume <id>` keeps the same session ID,** so one Nexus query covers every turn of a run.
- **Nexus `usage --json` shape:** `rows[].displayModel`, `subagents[].rows[]`, `grandTotals.cost` (subagents included), `unpriced`.
- **The `nexus claude demo` command is a one-shot toy** (tetris/snake, single HTML file). It's not usable for the race, but it confirmed the pattern: `claude -p --model X` on a shared profile, with settings untouched.
- **Headless Chromium needs SwiftShader flags** to render WebGL (set in `snapshot.py`).
- **Long foreground commands can get killed** (exit 137), and Claude Code background tasks are capped at 10 minutes. **Launch real races detached:** `nohup uv run buildoff race ... > ~/gta-race-runs/<id>.log 2>&1 & disown`, then watch `logs/turns.jsonl`.
- **In zsh, never name a variable `path`.** It's tied to `$PATH`, so `read ... path` wipes every command. Use bash for loops over CSVs.
- **USD conversion goes through Blender** (`brew install --cask blender`, 5.3). `usd-core` alone can read USD but can't write glTF with materials. Blender bundles `pxr`, so the converter reads joints in-process without a pip install.
- **`hf download --include` patterns:** `"<folder>/*"` matches nested files (the `*` crosses `/`). One call with many `--include` flags downloads only the curated folders, about 120 MB for 45 props.
- **USDCraft stage layout:** `/Asset/Links/<link>/Visuals/...` holds the render meshes, `/Asset/Links/<link>/Collisions/...` holds collision meshes (purpose `guide`), `/Asset/Joints/*` holds `PhysicsRevoluteJoint`/`PhysicsPrismaticJoint` with body0/body1, and `/Asset/Looks/*` holds UsdPreviewSurface materials.
- **`/code-cleanup` can only be run by the user.** The agent can't invoke it; ask the user to type it.
- **The base repo commits `node_modules/`** without execute bits and with another OS's native binaries, so `vite` fails with "Permission denied". Seeding skips it (along with `assets/` and `dist/`) and runs a clean `npm install`. In the first smoke test, one model silently spent budget fixing it, which made that race unfair.
- **Screenshots of the game need three things:** (1) wait for `networkidle`; (2) settle about 12 s, because the base game parses its FBX/GLB files between downloads and takes about 9 s headless; (3) click the center with a **pointer-lock shim** installed (`POINTER_LOCK_SHIM` in `snapshot.py`), since headless Chromium never grants pointer lock and "Click to Play" would never go away. Without these, every frame is a T-posed first frame or the menu.
- **A model can block itself on a never-ending server.** In the dry run, Kimi ran `npm run preview` in the foreground; its session sat blocked for 35 min with no spend. Opus's `vite preview` outlived its turn (orphaned, ppid 1). Both are now handled by the stall timeout and `_kill_strays`.
- **trimesh appends random suffixes** to node names with several primitives (`_3ec909`). The catalog reads names from the glTF JSON chunk instead, to stay deterministic.
- **`rsync --exclude dist`** also skips `node_modules/vite/dist`. Use `--exclude /dist` for top-level only. **`rsync --delete`** is blocked by a safety check; copy into a fresh folder instead.
- **`xargs -I{} sh -c '...'` over long command strings** fails with "command line cannot be assembled". Use a bash script with `xargs -0 -n 1 bash -c 'fn "$0"'`.
- **Rocketbox** is a 4.1 GB repo (about 10 GB of avatar files, mostly 4K TGA textures). We only fetch `Export/<Name>.fbx` and `Textures/*_color.tga` per avatar (448 files, about 3.5 GB) via `media.githubusercontent.com` (LFS) with raw fallback.
- **JSON has no `Infinity`.** USD stores unlimited joints as ±inf; Python's `json.dumps` writes `Infinity`, which browsers' `JSON.parse` rejects (jq silently tolerates it). Unlimited limits are now `null`, and the catalog and converter write with `allow_nan=False`. Every JSON/JSONL in the dataset was checked with Node's `JSON.parse`.
- **The HF cache lives under `~/.cache`.** Any "skip `.cache`" filter (for download leftovers) must test the path *relative to* the snapshot folder, or it skips every file (this bit both `copy_core` and the fetch summary).
- **The catalog's facts for Rocketbox/Kenney come from upstream `metadata.jsonl`.** Their glbs are meshopt-compressed, and trimesh can't decode them.
- **To check a .glb visually,** load it in a headless three.js page with Playwright (SwiftShader flags) and screenshot it. That's how the GPU, the props and the contact sheet were verified.

## 6. Where things are

- `README.md`: how to run, the output layout, a code map
- A diagram of the system is in `README.md` (Mermaid)
- `harness/`: the code. Start at `race.py`, then `runner.py`.
- `prompts/`: `game_spec.md` (placeholder), `run_rules.md` (the DONE.md and index.html contract), `nudge.md`, `smoke_spec.md`
- `assets/`: `gpu/` (CC0 GPU), `cars/` (Kenney CC0), `props/` (USDCraft, Apache 2.0, plus `manifest.json`). Each folder keeps its license file.
- `scripts/convert_usdcraft.py`: the USDCraft → .glb converter, run in Blender
- `~/gta-race-runs/`: race outputs. The test races there (`smoke-*`, `stress-001`, `cleanup-verify`) are disposable.

Cheap checks:
```bash
uv run ruff check harness scripts
uv run buildoff smoke   # ~$0.30, ~2 min, real setup
```

## 7. Spend log

| What | Approx. cost |
|---|---|
| Harness development and tests (smoke, stress, leak test, verify) | ~$2 |
| Smoke tests on the seeded base game (3 runs) | ~$1 |
| $5 dry run (`test-5usd-001`) | $8.77 (Kimi $3.75 + Opus $5.02) |

## 8. Next up

The user's order, set 2026-11-20:
1. ~~Code cleanup~~ ✅
2. ~~README + onboarding update~~ ✅
3. ~~Replication setup~~ ✅ (doctor, build_assets, byte-identical rebuild)
4. ~~Decide what goes in git~~ ✅
5. ~~Back to the prompts~~ ✅ **Locked 2026-11-20, tag `prompt-v1`.** sha256: game_spec `729ffffa…a0b2`, run_rules `e32a44a0…6a6e`, nudge `e9cd6279…1902`.
   - Decided: **the harness runs `npm install && npm run build` after each turn** and screenshots `dist/index.html`. A failed build means the turn isn't playable. (The base's `index.html` imports `three` by bare name, so it can't be served statically.) **The harness doesn't do this yet.** `snapshot.screenshot` still serves the workspace root.
   - In the prompt, the tiers are **Tier 1 Small-time / Tier 2 Getaway / Tier 3 Crew / Tier 4 Kingpin**. The "GTA 1–4" labels are for the video only, so the models don't reach for a real product.
   - Decided: **models see the tier ladder** (as goals) and **know they have about $100 of compute**. They are *not* told they're racing another model.
   - The prompt promises assets at **`public/assets/gt-gpu/{gpu,cars,props}`**. Seeding must put them there (Vite serves `public/` at the site root).

After that (the user's order, 2026-11-20):
1. ~~Harness seeding + per-turn Vite build~~ ✅
2. ~~Smoke test on the real setup~~ ✅ (`smoke-seed-002`: Kimi $0.12 / 82 s, Opus $0.13 / 39 s, both playable)
3. ~~Update the team in Notion~~ ✅ (Nov 20: added an "Update: Nov 20, 2026" section, milestone, check-in and appendix note): the internal program brief (link in CLAUDE.local.md) (status, decisions, what's built so far)
4. ~~Thin CLI + `AGENTS.md`~~ ✅ `uv run buildoff doctor|assets|smoke|race` (race over $2 requires `--yes`). `AGENTS.md` is for people who clone the repo and point an agent at it; `CLAUDE.md` imports it.
5. $5–10 test runs of each model on the locked prompt, then the full race
6. ~~HUMANS.md~~ ✅ A blog-style explainer of the premise, setup and rules (via the blog-writer skill), linked from the README. Its **Results** section is empty: fill it after the race, and it becomes the blog post.
