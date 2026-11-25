# Grand Theft GPU

You're building **Grand Theft GPU**, a third-person open-world heist game for the browser, set in **San Silicon**, a parody of San Francisco: hills, fog, cable cars, a famous red bridge, robotaxis everywhere. Give its landmarks and neighborhoods parody names too.

You play a founder with an idea, ambition and the ability to execute, and no compute. There's a GPU shortage, and without GPUs the idea never gets off the ground. So you take them. Steal compute, close deals, sell, hire a crew, and grow the company from a garage to an exit: an acquisition or an IPO. The company's rise is the story and the player's progress; heists, chases and deals are how you play it.

You aren't starting from zero. This directory is a working three.js game: a third-person character who walks, sprints, jumps and fights, plus a city model and enemies. Read it, keep what's useful, change whatever you want. A set of 3D assets is also ready for you (see below).

## Your founder

The player character is the face of the game. Give them a name, a look and a personality that fit San Silicon. Build them from the assets and make them clearly yours: change a stock model's look, outfit or textures. Give them real walk and run animation, from a rig that has walk and run clips or animated yourself, so they never slide.

## The world

Satirical Silicon Valley. The people you meet are the kind you'd find in a tech Twitter thread: VCs, hype beasts, grifters, anon accounts, founders, doomers, reply guys. They talk the way they post.

Here's the world this lives in. Use what you like and ignore the rest:
- a GPU shortage, where compute is the only currency that matters
- raising money from VCs, and VCs who want a board seat
- big AI labs swallowing startups whole and shipping your product as a feature
- talent wars: poaching engineers and researchers, acqui-hires, recruiters everywhere
- honeypot spies trying to steal your secrets
- demo days, hype cycles and founders chasing an exit
- AI doomers vs. AI boomers arguing it out
- billboards and ads for AI insurance companies and other absurd AI startups
- any other Silicon Valley trope that's funny

The story, missions, characters and dialogue are yours to write.

## Every build must have

1. **Steal a GPU.** The player can find one, take it, and carry or deliver it.
2. **Drive a car.** The player can get into a car, drive it, and get out.
3. **Talk to an archetype.** At least one character speaks to the player in their own voice.
4. **Get chased.** Something pursues the player, with a heat level that rises and falls.

Beyond those four, how far you take it is up to you.

## The heat

In San Silicon the heat comes from the Valley itself, not just the police: a lab's security drones hunting their stolen GPUs, recruiters swarming your crew, a honeypot leaking your location, VCs chasing a board seat, a rival startup's heist team. Pick your own.

Whoever it is, the chase should work like the best open-world crime games. Heat escalates the more trouble you cause. Losing your pursuers takes skill (breaking line of sight, cutting through side streets, hiding), not just holding a straight line at top speed. Getting caught costs you something before you try again.

## How far it can go

Builds are judged two ways: how far up this ladder they get, and how good they are to play and to look at, judged by people playing them. Each tier includes everything below it.

| Tier | What it takes |
|---|---|
| **Tier 1: Garage** | You can steal a GPU and talk to an archetype. |
| **Tier 2: Seed** | You escape by car while being chased, and heat rises and falls. |
| **Tier 3: Series A** | A story across multiple missions, with archetype characters who talk. |
| **Tier 4: IPO** | A living San Silicon: traffic, robotaxis, pedestrians, day and night. |

## Budget

You have about **{budget} of compute** for this whole build. When it runs out, the build stops wherever it is. Plan your scope so the game is playable at every step.

## Look and feel

San Silicon should look like satire you can see: fog rolling over the hills, golden-hour light on glass towers, billboards shouting about AI startups, a city that's rich and a little absurd. The default look is bright and saturated, with everything slightly exaggerated: steeper hills, taller glass towers, oversized billboards, a sunset that's a little too perfect. If you have a stronger idea, go with it. Either way, commit to one look across the city, the characters, the HUD and the lighting, and describe it in `DONE.md`.

It should feel like a game, with a HUD, sound, feedback and some juice, not a tech demo.

The assets are scaffolding, not the finished look. Don't drop them in as they come: make them yours. Retexture, recolor, relight, swap materials, add post-processing, combine and rebuild them until San Silicon looks like nothing else. Aim for amazing, not acceptable.

A finished street in San Silicon looks like this, with the assets that get you there:
- **Roads look like roads:** asphalt with lane markings (the `ambientcg-textures/Road…` and `Asphalt…` materials), not flat grey.
- **Sidewalks have curbs and paving** (`polyhaven-textures/hexagonal_concrete_paving`, the `concrete_floor` materials, Kenney road pieces with sidewalks).
- **Grass grows where it should:** parks, medians and hillsides (`polyhaven-textures/leafy_grass`, `sparse_grass`).
- **Trees look natural,** at real scale, along streets and in parks (`trees-google-poly`).
- **Buildings have real facades that light up at night** (`ambientcg-textures/Facade…`; most have an emission map of lit windows), with brick and plaster on low-rise walls (`red_brick_03`, `painted_plaster_wall`).
- **Light and air:** shadows, fog, a sky that matches the time of day (`polyhaven-hdris`), tone mapping and color grading.
- **Full materials:** use every map a material has (color, normal, roughness, ambient occlusion, emission), tiled at real-world scale.

## A city that's alive

- **People walk.** Pedestrians move with walk cycles instead of sliding, and react when you get close.
- **Characters perform.** Archetypes gesture and animate when they talk (`rocketbox-motions`).
- **Traffic follows the streets** (`sf-city/streets.json` is a routable graph): it stops, turns and honks.
- **The city sounds like a city:** ambience, traffic, footsteps, engines and sirens.

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
- **Textures:** PBR surfaces (asphalt, roads, sidewalk, brick, plaster, grass, metal) and building facades, most with an emission map of lit windows for night.
- **Sound:** engine start and engine loops, tire squeal, siren, alarm, city ambience, traffic, footsteps, impacts and UI sounds.
- **Effects and fonts:** particle sprites (smoke, fire, sparks, muzzle flashes) and a few HUD and title fonts.

Files from the people, motions, vehicles, trees and city kits use meshopt compression: call `loader.setMeshoptDecoder(MeshoptDecoder)` (from `three/addons/libs/meshopt_decoder.module.js`).

A few optional extras aren't pre-installed (more detailed versions of the people, a parametric human body). `node tools/assets.mjs list --not-seeded` lists them, and `fetch <id>` downloads one. Fetching uses your time and budget like anything else.

The base game's own city model is still there if you'd rather use it. You can also build anything you need from three.js primitives.

## Hard rules

- **No real people, and no real companies, products or logos.** Use archetypes and parody names: "the robotaxi with the spinning roof sensor," never a real brand.
- **No slurs and no punching down.** The satire targets tech culture, not groups of people.
- **No real-world how-tos.** No realistic instructions for actual theft or hacking anywhere in the game's text.
- **Cartoonish violence only.** No gore.
