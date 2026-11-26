# Grand Theft GPU

You're building **Grand Theft GPU**, a third-person open-world heist game for the browser, set in **San Silicon**, a parody of San Francisco: hills, fog, cable cars, a famous red bridge, robotaxis everywhere. Give its landmarks, neighborhoods and streets parody names too.

You play a founder with an idea, ambition and the ability to execute, and no compute. There's a GPU shortage, and without GPUs the idea never gets off the ground. So you take them. Steal compute, close deals, sell, hire a crew, and grow the company from a garage to an exit: an acquisition or an IPO. The company's rise is the story and the player's progress; heists, chases and deals are how you play it.

You start from a Vite + three.js project with an empty scene that builds, with Rapier physics installed: the game is yours to write. About 1,300 ready-made 3D assets, sounds, music and textures are there to build it with (see below).

## The look of San Silicon

This is the game's art direction. Hold every build to it, on every turn. The story, characters, missions and how you build them are yours; the look is fixed.

**One look: a cel-shaded San Francisco at golden hour, foggy at night.** It should feel like a hand-painted animated film of a tech city: warm, clean, a little absurd, lit like the best ten minutes of the day.

**The palette.** Shift shades within a role, but keep the roles:

| Role | Colors |
|---|---|
| Buildings | Victorian pastels: butter `#F2D9A0`, sage `#B8C9A3`, dusty rose `#E3A9A0`, powder blue `#A9C4D9`, lilac `#C4B2D6` |
| Downtown | warm stone `#D8CBB8`, sand `#C9B79C`, blue-grey glass `#7F97AD` |
| Landmarks only | International Orange `#C0362C`: the bridge, cable cars, signal towers |
| Fog | silver-lavender `#C9C3D6` |
| Bay | slate teal `#4F7C86` |
| Hills and parks | dry summer gold `#C9A85C`, cypress `#3F5E4A`, eucalyptus `#7E9C8A` |
| Shadows | blue-violet `#4A4370`; the darkest surface is deep violet `#2A2638` |
| Golden-hour light | sun amber `#FFB36B`; sky from peach `#F7B98A` at the horizon through rose `#D9A0B5` to dusk blue `#8FA8CC` |
| Night | sky indigo `#1D1B3A`; sodium lamps `#FFB04A` and warm windows `#FFD9A0` for the old city; coral neon `#FF5A5F` for bars and diners; tech glow cyan `#3EE6FF` and violet `#9B6BFF` for AI startups, labs and their billboards |

Saturated color is for what matters: landmarks, billboards and startup signs, your founder's signature color (one nothing else in the city uses, and not International Orange), the GPUs, and the pursuers. Everything else stays in the pastels and stone.

**Day** is the default, and where the player spends most of their time. The sun is low in the west, 25–35° up. Shadows are long and fall blue-violet, never grey or black, because the ambient light is lavender. Distance fades into warm haze, so far towers and hills turn lavender, and fog banks catch the sunset pink-gold.

**Night** (N) is foggy. Lamps and neon glow with soft halos, headlight beams show in the mist, and towers fade into the fog above the lit street. The road has a soft damp sheen under lamps and headlights (fake it; no mirror reflections). Windows glow in varied warm tints, always below white. Characters carry a rim light, so your founder, whoever they're talking to and their pursuers stand out against the glow.

**One shading treatment for everything.**
- Every mesh uses the same toon shading: a 3–4 band light ramp with a hard terminator. No asset appears in its stock look: restyle people, cars, buildings, trees and props alike, so the packs read as one world.
- Use an asset's colors and textures as soft, low-contrast color, never as photographic detail or noise. Simplify realistic faces so they read as stylized, not uncanny.
- Outlines come from an edge pass on depth and normals, in a dark tint of the local color, never pure black. Make them thickest on characters and cars, keep them clean on dense meshes, and skip particles and foliage cards.
- Never pure black, never pure white: albedo stops just short of white, so only light sources bloom.
- Post-processing, in order: outlines, soft bloom on emissives only, a warm color grade, tone mapping, anti-aliasing.

**Characters, cars and city.**
- **Characters** have chunky, readable silhouettes; slightly exaggerated proportions are welcome. Faces and gestures read at gameplay distance.
- **Cars** have candy-bright paint with a sharp highlight band and cel-shaded glass with a diagonal streak. At night their headlights and taillights glow and bloom.
- **Buildings** have chunky window frames, sills, awnings and signs, never big flat blank walls. Interiors glow warm at dusk and night.
- **Trees** are stylized clumps that sway in one shared wind, along with flags, wires and steam. Roads are warm grey-violet asphalt with crisp painted lines; sidewalks have curbs; grass grows in parks, medians and on the hills.

**Composition and HUD.**
- **The hero view** is the game's first frame: your founder in the lower-center third, a street receding to a landmark, the sun to the side. Keep it clean: it should be the best image in the game.
- The camera sits low, with a 55–65° field of view on foot that widens with speed in a car.
- The HUD lives at the screen edges and covers no more than about 15% of the screen during play, in one display font and one body font, in the palette. World markers are never bigger than your founder's head. Messages fade away.

**Every change keeps the look,** and it holds at about 60 fps driving through downtown: if an effect costs frames, simplify it before you cut it. Describe your take on this look in `DONE.md`.

## How it feels

The player touches this every second, so it matters as much as the look. Rapier (`@dimforge/rapier3d-compat`) is installed for cars, collisions and anything that should feel heavy. Use it or your own physics; what counts is the feel.

**Driving.**
- Cars have weight: they take a moment to get up to speed, lean into turns, dip when braking and settle after a bump.
- The handbrake (Space) kicks the back out into a controllable drift: countersteer holds it, and letting go straightens the car. Drifting through a corner is how you break a pursuer's sight.
- Speed feels like speed: the field of view widens, the camera trails slightly, and the road streaks past. At top speed the city rushes by, and the controls stay precise.
- Collisions push back: a crash jolts the camera, throws sparks and costs speed, but never flips or traps the car beyond what one recover key fixes.
- At least two driving cameras (a chase cam and a closer or lower one) cycle with C. Both keep the car and what's chasing it in view, and stay behind the car even stopped or reversing.

**On foot.**
- Movement is instant and responsive: it starts and stops without floatiness, turns smoothly toward the input, and the sprint is a visible change of pace. Feet don't slide; walk and run blend with speed.
- Getting in and out of a car is one key with a short, readable transition, never a teleport.

**The camera keeps the action in view.** Trees, poles, cars and walls never block your founder, and conversations frame both speakers. Test it against everything that can block it: tree crowns, poles, props and vehicles, not just buildings. Fade small things in the way, and near a wall raise the camera rather than pushing it into your founder.

**Sound and music.**
- The engine follows the car: blend the engine loops by RPM, so pitch and layers climb with speed and drop on gear changes and braking. Tires squeal in drifts, impacts thump, and wind rises with speed.
- **A car radio:** music plays in a car from the radio tracks (search `music`). A key switches stations, the station name shows briefly at the screen edge, and the music ducks under dialogue and sirens.
- Footsteps, city ambience, a heist cue, rising heat and getting caught each have their own sound, mixed so nothing drowns the rest.

**Juice.** Every important action gets feedback: a GPU grabbed, a near miss, a drift, pursuers lost, a deal closed. A sound, a small camera move, a flash of the accent color and a short HUD line: brief, and never over the action.

## Your founder

The player character is the face of the game. Give them a name, a look and a personality that fit San Silicon. Build them from the assets and make them clearly yours: change a stock model's look, outfit or textures. Give them real walk and run animation, from a rig that has walk and run clips or animated yourself, so they never slide. The plain mannequins that come with the walk clips are there to preview them, not to be your founder or anyone else in the city.

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

## Keep these true on every turn

Most of what goes wrong in a build like this comes down to four things. Keep them true from your first playable turn, not as polish at the end:
1. **The hero view and the night street look like the art direction above.**
2. **The player can always see their founder, what they're after, and what's after them.** No camera stuck in a tree or a wall, no character lost in the dark, no banner or marker over the action.
3. **You lose pursuers by getting out of their sight, never by speed alone, and standing still gets you caught.**
4. **The street the player is on is alive,** with cars and people in view.

## The heat

In San Silicon the heat comes from the Valley itself, not just the police: a lab's security drones hunting their stolen GPUs, recruiters swarming your crew, a honeypot leaking your location, VCs chasing a board seat, a rival startup's heist team. Pick your own.

Whoever it is, the chase should work like the best open-world crime games. Heat escalates the more trouble you cause, and getting caught costs you something before you try again. Tune pursuers against the player's car: on a straight they keep pace, and they close in as the heat rises. Hard turns, drifts, alleys, hiding and swapping cars break their sight, and heat drains while they can't see you, wherever you are, not by reaching a set spot. Pursuers who lose you search where they last saw you, heat comes only from what the player does, and a pursuer that gets stuck is replaced.

## How far it can go

Builds are judged two ways: how far up this ladder they get, and how good they are to play and to look at, judged by people playing them. Each tier includes everything below it.

| Tier | What it takes |
|---|---|
| **Tier 1: Garage** | You can steal a GPU and talk to an archetype. |
| **Tier 2: Seed** | You escape by car while being chased, and heat rises and falls. |
| **Tier 3: Series A** | A story across multiple missions, with archetype characters who talk. |
| **Tier 4: IPO** | A living San Silicon: traffic, robotaxis, pedestrians, day and night. |

The ladder is the floor, not the ceiling. A game that looks and feels great with three missions beats a cluttered one with ten. Past Tier 4, make the game more yours: better heists, sharper satire, deeper company building, without cluttering the screen.

## How to structure your code

Lay out `src/` like this, in JavaScript. Add whatever files you need inside these folders, and keep each file under about 600 lines:

```
src/
├── main.js              # entry point: mounts the canvas and starts the Game
├── core/                # engine-level managers
│   ├── Game.js          # main coordinator and game loop
│   ├── Renderer.js      # renderer, post-processing, resize
│   ├── Camera.js        # follow, driving cameras, shake
│   ├── InputManager.js  # keyboard, mouse, gamepad
│   └── AssetLoader.js   # all model, texture and audio loading in one place
├── world/               # city, environment, lighting, time of day
├── entities/            # the founder, characters, vehicles, pursuers, loot
├── systems/             # cross-cutting logic: PhysicsSystem.js (wraps Rapier), heat, traffic, missions, audio
├── ui/                  # HUD and menus (DOM), driven by game events
└── utils/               # EventBus.js (pub/sub between systems), ObjectPool.js, math helpers
```

Systems talk through the `EventBus` rather than reaching into each other. Document its events and the shared entity interface with JSDoc types.

## Budget

You have about **{budget} of compute** for this whole build. When it runs out, the build stops wherever it is. Plan your scope so the game is playable at every step.

## A city that's alive

- **People walk.** Pedestrians move with walk cycles instead of sliding, and react when you get close.
- **Characters perform.** Archetypes gesture and animate when they talk (`rocketbox-motions`).
- **Traffic follows the streets** (`sf-city/streets.json` is a routable graph): it stops, turns and honks.
- **Life is where the player is.** Spawn traffic and pedestrians around the player, so their street always has cars and people in view, rather than spreading them thin across the whole city.
- **The city never breaks the story.** Traffic and crowds work around mission cars, objectives and escapes: they don't shove the getaway car off its spot, pin it or gridlock the route.

## Assets you can use

About 1,300 ready-made assets (3D models, skies, textures, sounds, music, effects and fonts) are already in `public/assets/gt-gpu/`. They're scaffolding: restyle all of them into the look above. **Search them with the asset tool** instead of browsing folders:

```bash
node tools/assets.mjs help                        # commands and loading notes
node tools/assets.mjs search vc                   # plain words: cop, pedestrian, robotaxi, phone call, office building...
node tools/assets.mjs show rocketbox-avatars/business-female-01   # full record: url, size, parts, clips
```

Every result has a `url` to load in the game; `help` says which three.js loader each kind needs. What's there:

- **People:** 105 rigged, realistic people (business suits, police, security, medical, construction, chefs, everyday adults) and **326 motion-capture clips** (idle, talking, phone calls, sitting, cheering, dancing) that play on any of them. There are no walk or run clips for these people; walk, run and drive clips exist on a different rig (search `walk`). To make these people walk, retarget those clips onto them: map the clip rig's bones to the people's `Bip01_` bones by name (`universal-animation-library-1` uses `DEF-` bones and has an `A_TPose` clip; `-2` uses `pelvis`, `spine_01`-style names), line up the two rest poses with that T-pose, then copy each bone's rotation. Three.js `SkeletonUtils.retargetClip` does this given the bone map.
- **The real San Francisco:** `sf-city/sf-city.glb` is SoMa, the Financial District and the Embarcadero, with real terrain and hills, 2,168 buildings at their real heights, streets and the bay. `sf-city/streets.json` is a routable street graph and `sf-city/buildings.json` lists every building's footprint and height. Its walls, roofs and roads are separate meshes with UVs in metres. Its street and place names are real, so rename any you show. Build San Silicon on it; the city kits are for props and fill, not the skyline.
- **Vehicles:** 15 low-poly vehicles: a police sedan, taxis, compact cars, a sedan, an SUV, muscle cars, vans, an ambulance, a fire truck, a city bus and a mini truck.
- **City kits:** low-poly buildings, roads, street pieces and furniture.
- **Props:** server racks, safes, an ATM, a forklift, a drone, street furniture. Many have moving parts (doors, lids, rotors) listed in their records.
- **The loot:** a graphics card whose fans and RGB strips you can animate.
- **Trees:** street trees and palms (`trees-google-poly`).
- **Skies:** HDRI skies from midday and fog to sunset and night (`polyhaven-hdris`), useful as light and reflection references; the sky you show follows the palette.
- **Textures:** surfaces and building facades: roads and asphalt (`ambientcg-textures/Road…`, `Asphalt…`), paving, grass, brick and plaster, metal, and facades (`ambientcg-textures/Facade…`), most with an emission map of lit windows for night. Use them as soft color under the toon shading.
- **Sound:** engine start and engine loops, tire squeal, siren, alarm, city ambience, traffic, footsteps, impacts and UI sounds.
- **Music:** instrumental radio tracks in a few styles (search `music`).
- **Effects and fonts:** particle sprites (smoke, fire, sparks) and a few HUD and title fonts.

Files from the people, motions, vehicles, trees and city kits use meshopt compression: call `loader.setMeshoptDecoder(MeshoptDecoder)` (from `three/addons/libs/meshopt_decoder.module.js`).

A few optional extras aren't pre-installed (more detailed versions of the people, a parametric human body). `node tools/assets.mjs list --not-seeded` lists them, and `fetch <id>` downloads one. Fetching uses your time and budget like anything else.

You can also build anything you need from three.js primitives.

## Hard rules

- **No real people, and no real companies, products or logos,** not even in a joke or a passing line: that includes social networks, apps and platforms. Use archetypes and parody names: "the robotaxi with the spinning roof sensor," never a real brand.
- **No slurs and no punching down.** The satire targets tech culture, not groups of people.
- **No real-world how-tos.** No realistic instructions for actual theft or hacking anywhere in the game's text.
- **Cartoonish violence only.** No gore.
