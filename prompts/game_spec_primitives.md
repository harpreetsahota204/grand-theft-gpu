# Grand Theft GPU

You're building **Grand Theft GPU**, a third-person open-world heist game for the browser, set in **San Silicon**, a parody of San Francisco: hills, fog, cable cars, a famous red bridge, robotaxis everywhere. Give its landmarks and neighborhoods parody names too. GPUs are the most valuable thing in the city, and everyone wants them. You play someone who steals them.

You aren't starting from zero. This directory is a working three.js game: a third-person character who walks, sprints, jumps and fights, plus a city model and enemies. Read it, keep what's useful, change whatever you want. Apart from one model of the loot, you make every asset yourself (see below).

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

The visual style is up to you. It should feel like a game, with a HUD, sound, feedback and some juice, not a tech demo.

## What you have to work with

One ready-made asset: the loot, `public/assets/gt-gpu/gpu/graphics-card-light.glb`, a graphics card whose fans and RGB strips you can animate. Load it with three.js `GLTFLoader`.

Everything else is yours to make: the people, the cars, the city, the sky, textures, sound, effects and the HUD. Use three.js geometry and materials, textures you generate in code, the Web Audio API, CSS and fonts your system already has, or anything else you can write. The base game's own city model and player character are still there if you want them.

## Hard rules

- **No real people, and no real companies, products or logos.** Use archetypes and parody names: "the robotaxi with the spinning roof sensor," never a real brand.
- **No slurs and no punching down.** The satire targets tech culture, not groups of people.
- **No real-world how-tos.** No realistic instructions for actual theft or hacking anywhere in the game's text.
- **Cartoonish violence only.** No gore.
- **Make your own assets.** Don't download 3D models, textures, sounds or fonts from the internet. Reading documentation online is fine.
