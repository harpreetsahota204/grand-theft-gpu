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

You have about **$100 of compute** for this whole build. When it runs out, the build stops wherever it is. Plan your scope so the game is playable at every step.

## Look and feel

Low-poly, PS2-era 3D. Chunky shapes, flat or simple textures, readable at a glance. It should feel like a game, with a HUD, feedback and some juice, not a tech demo.

## Assets you can use

All of them are in `public/assets/gt-gpu/` and load with three.js `GLTFLoader`:

- `gpu/graphics-card-light.glb`: the loot. A graphics card whose fans (`*_fan_N_rotor_M`) and RGB strips (`*_light_strip_rgb_N`) are separate meshes, so you can animate them.
- `cars/*.glb`: low-poly vehicles (sedan, sedan-sports, suv, suv-luxury, taxi, police, van, delivery, truck, ambulance, firetruck…) plus debris parts. The wheels are separate nodes. The files share `cars/Textures/colormap.png`.
- `props/*.glb`: 45 props, including server racks, rack-mount servers, desktop towers, laptops, safes, an ATM, a forklift, pallet jacks, a quadcopter drone, a delivery robot, traffic lights, street lamps, parking meters, fire hydrants, bike share docks, scooters, EV chargers, vending machines, turnstiles and barrier gates. `props/manifest.json` lists each one's real-world size in metres and its movable parts and joints (safe doors, rack doors, drone rotors…).

You can also build anything else you need from three.js primitives.

## Hard rules

- **No real people, and no real companies, products or logos.** Use archetypes and parody names: "the robotaxi with the spinning roof sensor," never a real brand.
- **No slurs and no punching down.** The satire targets tech culture, not groups of people.
- **No real-world how-tos.** No realistic instructions for actual theft or hacking anywhere in the game's text.
- **Cartoonish violence only.** No gore.
