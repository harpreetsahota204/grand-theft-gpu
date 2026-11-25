# Grand Theft GPU

You're building **Grand Theft GPU**, a third-person open-world heist game for the browser, set in **San Silicon**, a parody of San Francisco: hills, fog, cable cars, a famous red bridge, robotaxis everywhere. Give its landmarks and neighborhoods parody names too.

You play a founder with an idea, ambition and the ability to execute, and no compute. There's a GPU shortage, and without GPUs the idea never gets off the ground. So you take them. Steal compute, close deals, sell, hire a crew, and grow the company from a garage to an exit: an acquisition or an IPO. The company's rise is the story and the player's progress; heists, chases and deals are how you play it.

You aren't starting from zero. This directory is a working three.js game: a third-person character who walks, sprints, jumps and fights, plus a city model and enemies. Read it, keep what's useful, change whatever you want. Apart from one model of the loot, you make every asset yourself (see below).

## Your founder

The player character is the face of the game. Give them a name, a look and a personality that fit San Silicon. Give them a distinctive look and real walk and run animation, so they never slide.

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

Aim for amazing, not acceptable. A finished street in San Silicon looks like this:
- **Roads look like roads:** asphalt with lane markings, not flat grey.
- **Sidewalks have curbs and paving.**
- **Grass grows where it should:** parks, medians and hillsides.
- **Trees look natural,** at real scale, along streets and in parks.
- **Buildings have real facades that light up at night**, with brick and plaster on low-rise walls.
- **Light and air:** shadows, fog, a sky that matches the time of day, tone mapping and color grading.
- **Real materials:** surfaces with texture, bumps and shine (color, normal and roughness maps you generate in code), tiled at real-world scale, not flat colors.

## A city that's alive

- **People walk.** Pedestrians move with walk cycles instead of sliding, and react when you get close.
- **Characters perform.** Archetypes gesture and animate when they talk.
- **Traffic follows the streets:** it stops, turns and honks.
- **The city sounds like a city:** ambience, traffic, footsteps, engines and sirens.

## What you have to work with

One ready-made asset: the loot, `public/assets/gt-gpu/gpu/graphics-card-light.glb`, a graphics card whose fans and RGB strips you can animate. Load it with three.js `GLTFLoader`.

Everything else is yours to make: the people, the cars, the city, the sky, textures, sound, effects and the HUD. Use three.js geometry and materials, textures you generate in code, the Web Audio API, CSS and fonts your system already has, or anything else you can write. The base game's own city model and player character are still there if you want them.

## Hard rules

- **No real people, and no real companies, products or logos.** Use archetypes and parody names: "the robotaxi with the spinning roof sensor," never a real brand.
- **No slurs and no punching down.** The satire targets tech culture, not groups of people.
- **No real-world how-tos.** No realistic instructions for actual theft or hacking anywhere in the game's text.
- **Cartoonish violence only.** No gore.
- **Make your own assets.** Don't download 3D models, textures, sounds or fonts from the internet. Reading documentation online is fine.
