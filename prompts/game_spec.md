# Grand Theft GPU

You're building **Grand Theft GPU**, a third-person open-world heist game for the browser, set in **San Silicon**, a parody of San Francisco: hills, fog, cable cars, a famous red bridge, robotaxis everywhere. Give its landmarks and neighborhoods parody names too. GPUs are the most valuable thing in the city, and everyone wants them. You play someone who steals them.

You aren't starting from zero. This directory is a working three.js game: a third-person character who walks, sprints, jumps and fights, plus a city model and enemies. Read it, keep what's useful, change whatever you want. A set of 3D assets is also ready for you (see below).

## The world

Satirical Silicon Valley. The people you meet are the kind you'd find in a tech Twitter thread: VCs, hype beasts, grifters, anon accounts, founders, doomers, reply guys. They talk the way they post.

Here's the world this lives in. Use what you like and ignore the rest:
- raising money from VCs
- poaching top engineers and researchers to join your crew
- honeypot spies trying to steal your secrets
- AI doomers vs. AI boomers arguing it out
- billboards and ads for AI insurance companies and other absurd AI startups
- any other Silicon Valley trope that's funny

The story, missions, characters and dialogue are yours to write.

## Every build must have

1. **Steal a GPU.** The player can find one, take it, and carry or deliver it.
2. **Drive a car.** The player can get into a car, drive it, and get out.
3. **Talk to an archetype.** At least one character speaks to the player in their own voice.
4. **Get chased.** Something pursues the player, with a heat or wanted level that rises and falls.

Beyond those four, how far you take it is up to you.

## How far it can go

Builds are judged on how far up this ladder they get. Each tier includes everything below it.

| Tier | What it takes |
|---|---|
| **Tier 1: Small-time** | You can steal a GPU. |
| **Tier 2: Getaway** | You escape by car while being chased, and heat rises and falls. |
| **Tier 3: Crew** | A story across multiple missions, with archetype characters who talk. |
| **Tier 4: Kingpin** | A living San Silicon: traffic, robotaxis, pedestrians, day and night. |

## Budget

You have about **{budget} of compute** for this whole build. When it runs out, the build stops wherever it is. Plan your scope so the game is playable at every step.

## Look and feel

The visual style is up to you. It should feel like a game, with a HUD, sound, feedback and some juice, not a tech demo.

## Assets you can use

About 1,300 ready-made assets (3D models, skies, textures, sounds, effects and fonts) are already in `public/assets/gt-gpu/`. **Search them with the asset tool** instead of browsing folders:

```bash
node tools/assets.mjs help                        # commands and loading notes
node tools/assets.mjs search vc                   # plain words: cop, pedestrian, robotaxi, phone call, office building...
node tools/assets.mjs show rocketbox-avatars/business-female-01   # full record: url, size, parts, clips
```

Every result has a `url` to load in the game; `help` says which three.js loader each kind needs. What's there:

- **People:** 105 rigged, realistic people (business suits, police, security, medical, construction, chefs, everyday adults) and **326 motion-capture clips** (idle, talking, phone calls, sitting, cheering, dancing) that play on any of them. There are no walk or run clips for these people; walk, run and drive clips exist on a different rig (search `walk`).
- **The real San Francisco:** `sf-city/sf-city.glb` is SoMa, the Financial District and the Embarcadero, with real terrain and hills, 2,168 buildings at their real heights, streets and the bay. `sf-city/streets.json` is a routable street graph and `sf-city/buildings.json` lists every building's footprint and height. Its walls, roofs and roads are separate meshes with UVs in metres, so textures tile at real-world scale. Building San Silicon on top of it is up to you.
- **Vehicles:** 15 realistic low-poly vehicles: a police sedan, taxis, compact cars, a sedan, an SUV, muscle cars, vans, an ambulance, a fire truck, a city bus and a mini truck.
- **City kits:** low-poly buildings, roads, street pieces and furniture.
- **Props:** server racks, safes, an ATM, a forklift, a drone, street furniture. Many have moving parts (doors, lids, rotors) listed in their records.
- **The loot:** a graphics card whose fans and RGB strips you can animate.
- **Trees:** street trees and palms.
- **Skies:** HDRI skies from midday and fog to sunset and night, for lighting and background.
- **Textures:** PBR surfaces (asphalt, sidewalk, brick, plaster, grass, metal) and building facades in day and night versions, the night ones with lit windows.
- **Sound:** engine start and engine loops, tire squeal, siren, alarm, city ambience, footsteps, impacts and UI sounds.
- **Effects and fonts:** particle sprites (smoke, fire, sparks, muzzle flashes) and a few HUD and title fonts.

Files from the people, motions, vehicles, trees and city kits use meshopt compression: call `loader.setMeshoptDecoder(MeshoptDecoder)` (from `three/addons/libs/meshopt_decoder.module.js`).

A few optional extras aren't pre-installed (more detailed versions of the people, a parametric human body). `node tools/assets.mjs list --not-seeded` lists them, and `fetch <id>` downloads one. Fetching uses your time and budget like anything else.

The base game's own city model is still there if you'd rather use it. You can also build anything you need from three.js primitives.

## Hard rules

- **No real people, and no real companies, products or logos.** Use archetypes and parody names: "the robotaxi with the spinning roof sensor," never a real brand.
- **No slurs and no punching down.** The satire targets tech culture, not groups of people.
- **No real-world how-tos.** No realistic instructions for actual theft or hacking anywhere in the game's text.
- **Cartoonish violence only.** No gore.
