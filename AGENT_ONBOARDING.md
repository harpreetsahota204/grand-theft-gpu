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
| Game prompt (`prompts/game_spec.md`, `run_rules.md`, `nudge.md`) | 🔒 **LOCKED 2026-11-20**, git tag `prompt-v1`. Do not edit without the user's explicit OK; any change is a new tag (`prompt-v2`) and invalidates comparisons with earlier runs. |
| Harness seeding + per-turn Vite build + gameplay screenshots | ✅ `harness/seed.py`, `snapshot.build`. The smoke test on the seeded base (`smoke-seed-002`) passed for both models: turn 0 builds, both added the GPU from our assets, and the screenshots show gameplay. |
| Scoring checklist (pass/fail checks per tier, for judges) | ⬜ The tiers are in the prompt; the detailed checks are still to write |
| $5 test run of each model on the locked prompt | 🔄 Running (`test-5usd-001`, started 2026-11-20). Turn 0 clean for both. |
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
| $5 test race (`test-5usd-001`) | up to $10 |

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
