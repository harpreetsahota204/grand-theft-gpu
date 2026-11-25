# Two Models, $100 Each, One Heist Game: Inside the GTA Build-Off

Models, Benchmarks, Agents

_Kimi K3.1 Pro and Claude Opus 5.5 each get $100 and the same locked prompt to build a GTA-style heist game, alone, in Claude Code. This is how the race is set up, what each model is given, and how we keep it fair._

GTA 6 took 4,811 days to arrive after GTA V. Here, each model gets $100.

That's the whole setup. Give two frontier-class models the same budget, the same starting code, the same assets and the same instructions, then step away. Neither model knows it's in a race. Each one builds, with a critic made from a fresh copy of itself reviewing every turn, until the money runs out.

The prompt was the easy part. The hard part is making sure the model is the only thing that differs between the two runs.

## **Key Takeaways**

* Both models run headless in Claude Code with identical flags, tools, files and settings. The only difference is the model: `kimi-k3p1-pro` (Kimi K3.1 Pro, routed to Fireworks by Nexus) or `claude-opus-5-5` (Claude Opus 5.5).
* Spend is metered by `nexus claude usage`, not by Claude Code. In testing, Claude Code priced a Kimi call at $0.060, while list price for the same tokens was $0.030.
* Each model starts from a working three.js game pinned to one commit, plus about 1,300 ready-made assets (or, in the primitives race, only the GPU it has to steal).
* A run keeps going until the $100 runs out. After every turn, a critic (a fresh copy of the same model that didn't build the game) plays it and tells the builder what to fix next. The critic's verdict never ends the run and never counts as the score: the builds are scored afterwards against a checklist we locked before the race. A watchdog kills it early if any other model shows up in its usage.
* Every turn leaves a git commit, a build result and a gameplay screenshot, every review keeps the critic's own screenshots and notes, and every transcript line is timestamped, so the race video can be cut from the logs.
* The whole setup is reproducible: `uv sync`, `uv run buildoff doctor`, then `uv run buildoff smoke` for a few dollars.

## **What are the models racing to build?**

The game is **Grand Theft GPU**. It's a third-person heist game set in **San Silicon**, a parody of San Francisco: hills, fog, cable cars, a famous red bridge, and robotaxis everywhere. You play a founder with an idea and no compute. There's a GPU shortage, so you steal GPUs, close deals and hire a crew, growing the company from a garage to an exit. The heat comes from the Valley itself: lab security, recruiters, honeypots, VCs who want a board seat.

The cast comes straight out of a tech Twitter thread: VCs, hype beasts, grifters, anon accounts, founders, doomers, reply guys. They're archetypes, never real people, and the brands are parodies too. The robotaxi is "the one with the spinning roof sensor," never a named company.

The prompt gives the models a world to play in and leaves the story to them. Raising money from VCs, poaching engineers, honeypot spies, doomers arguing with boomers, billboards for AI insurance startups: all of it is offered as inspiration, and none of it is required.

What *is* required, in every build:

1. **Steal a GPU.** Find one, take it, carry or deliver it.
2. **Drive a car.** Get in, drive, get out.
3. **Talk to an archetype.** At least one character who speaks in their own voice.
4. **Get chased.** A pursuer, with heat that rises and falls.

## **How do you score a game nobody has seen yet?**

With a ladder the models can see, plus how good the game is to play and look at. Each tier includes everything below it, and the tiers follow the player's startup, from a garage to an IPO.

| Video label | Tier | Unlocks when |
| --- | --- | --- |
| GTA 1 | Garage | You can steal a GPU and talk to an archetype |
| GTA 2 | Seed | You escape by car while being chased, and heat rises and falls |
| GTA 3 | Series A | A story across multiple missions, with archetype characters who talk |
| GTA 4 | IPO | A living San Silicon: traffic, robotaxis, pedestrians, day and night |

The "GTA 1–4" labels are for the video. Inside the prompt, the tiers are only called Garage through IPO, so the models aren't nudged toward copying a real game.

**Good to know. Do the models know their budget?**
Yes. The prompt states the race's real budget ("about $100 of compute" in a $100 race) and asks them to keep the game playable at every step, and every later prompt says how much they've spent so far. Earlier versions said $100 even in $25 test runs, and Opus planned a $100 game and spent its whole budget in one turn. The prompt doesn't say they're racing anyone, and the harness files a model can read have every comment and docstring stripped, so they don't say so either.

## **What does each model start with?**

Starting from an empty folder would turn the race into "who sets up three.js fastest." So both models start from the same working game and the same asset pack.

* **The base game:** [kartik786-git/gta-clone-threejs](https://github.com/kartik786-git/gta-clone-threejs), a third-person three.js game with walking, sprinting, jumping, melee and enemies, plus a city model. It's fetched at commit `babb623` for every race and is not redistributed here. It has no cars.
* **About 1,300 assets,** pre-installed in every workspace (about 650 MB) and published as the Hugging Face dataset [harpreetsahota/grand-theft-gpu-assets](https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets), with every folder's license and attribution:
  * **105 rigged people** from [Microsoft Rocketbox](https://github.com/microsoft/Microsoft-Rocketbox) (MIT): business suits, police, security, medical, construction, everyday adults. There are no animals or children, and avatars in religious dress or swimwear were left out so no model could cast them as the villains of a satire.
  * **326 motion-capture clips** on the same skeleton (idle, talking, phone calls, sitting, dancing), plus 89 walk/run/drive clips from [Quaternius](https://quaternius.com) (CC0) on a different rig.
  * **The real San Francisco:** SoMa to the Embarcadero, built from OpenStreetMap and USGS elevation. It has the hills, 2,168 buildings at their real heights, streets, the bay, and a routable street graph. Real building names are stripped.
  * **15 realistic low-poly vehicles,** all at real size and facing the same way: a police sedan, taxis, compact cars, an SUV, muscle cars, vans, an ambulance, a fire truck and a city bus, from Objaverse artists (CC-BY 4.0, every artist credited) and Quaternius (CC0).
  * **664 Kenney city pieces** (CC0): buildings, roads and furniture.
  * **45 props** from [NVIDIA USDCraft-10K](https://huggingface.co/datasets/nvidia/USDCraft-10K) (Apache 2.0): server racks, safes, an ATM, a forklift, a drone. We converted them from OpenUSD to glTF, keeping their moving parts and joints.
  * **The loot:** a CC0 graphics card from [Grab3D](https://grab3d.com/models/electronics/graphics-card/) with animatable fans and RGB strips.
  * **Looks and sound:** 8 HDRI skies and 16 PBR textures from [Poly Haven](https://polyhaven.com), 20 materials from [ambientCG](https://ambientcg.com) (office facades in day/night pairs, the night ones with lit windows), all CC0; 8 trees and palms (CC-BY 3.0, every artist credited); engine, tire, alarm and footstep sounds from OpenGameArt (CC0 and CC-BY 3.0) plus police and ambulance sirens, crashes, a horn and downtown traffic from Freesound (CC0); Kenney impact and UI sounds and particle sprites (CC0); and four OFL fonts for the HUD. The SF city's walls, roofs and roads have UVs in metres so these textures tile at real scale.
* **A search tool:** `node tools/assets.mjs search vc` finds business people, `search phone call` finds the phone clips, and so on, so a model never has to dig through 1,300 files. It can also `fetch` optional extras (more detailed people, Meta's parametric body) on demand, at the cost of its own time and budget. It's the only search tool, so it's also the one to use outside a race.
* **A screenshot tool:** `tools/screenshot` builds the game exactly the way the harness does, plays it in headless Chrome and saves a PNG. In one run it can play a scripted sequence: hold keys, alone or together (`--hold w+d:1500` drives and steers), wait, click, move the camera (`--look 300,0`) and save shots along the way (`--shot NAME`). Each call reloads the game, so before this a critic had to replay a whole mission one key at a time, and couldn't steer while driving. It saves a PNG the model opens with its Read tool. Without it, a model writes 3D code blind. Before adding it, we checked that both Kimi K3.1 Pro (through Nexus) and Opus can read images in Claude Code, so it helps both sides equally.

**Keep it honest.** The asset pack had a quiet bug, too. The web converter we mirror from had shrunk every Objaverse vehicle and every tree to about 1 m, and the vehicles faced different ways. A model would have parked a 1-metre fire truck next to 1.8-metre people, or spent its budget rescaling everything. We found it by rendering the pack, then set each model to its real size and the same heading by adding one transform node to each file. The geometry is untouched, and the change is recorded in each folder's `ATTRIBUTION.md`.

**Keep it honest.** The base game had a problem we only found by running it. It commits its own `node_modules`, without execute permissions and built for another OS. In the first smoke test, Kimi quietly spent part of its budget repairing the install, and Opus didn't. The harness now skips that folder and installs from the lockfile (`npm ci`) before the clock starts.

## **Why run the race twice?**

A rich asset pack makes better-looking games, but it also changes what the race measures. With finished people, cars and a real city handed over, the race mostly tests integration and game design: how well a model wires the parts together, and what it invents on top. The parts themselves are ours, and a viewer could easily credit the model for them.

The first dry run showed both sides. Opus wrote six missions, a wanted system and parody landmarks, all invention. It also put realistic people in the story scenes but made every pedestrian a recoloured copy of the base game's player, because our people have no walk animations. That was a shortcut around a gap in our pack, not a design choice.

So the comparison runs twice, same models and same rules:

| Race | What the models get | What it shows |
|---|---|---|
| **Asset race** (`--pack full`, `game_spec.md`) | The base game, about 1,300 assets and the asset search tool | What each model builds when good parts are on hand |
| **Primitives race** (`--pack primitives`, `game_spec_primitives.md`) | The base game and one model, the GPU. Everything else is made in code. Downloading assets is against the rules | How inventive each model is from scratch |

Both races keep the screenshot tool. It adds no content to the game, only a way for the model to look at its own work, and it's the same for both models. The gap between the two races is itself a result: it shows how much of a game's quality came from the parts, and how much from the model.

## **How does Nexus put Kimi inside Claude Code?**

Claude Code speaks one API: Anthropic Messages. [Nexus](https://docs.fireworks.ai/nexus) is a Fireworks CLI that points Claude Code at Fireworks, which serves that same API, so Claude Code can run open models like Kimi K3.1 Pro without changing anything else about how it works.

Three commands cover the whole setup:

```bash
nexus login             # sign in with your browser (or paste a Fireworks API key)
nexus claude            # route Claude Code through Fireworks
nexus claude status     # check the provider, where the key comes from, and the model
```

After `nexus claude`, any Claude Code session can pick a model by name. The harness asks for `--model kimi-k3p1-pro` on one side and `--model claude-opus-5-5` on the other, both fixed IDs rather than aliases that could move mid-race. Kimi turns run on Fireworks and bill to your Fireworks account. Claude turns keep using your Claude login. `nexus claude off` puts your original settings back.

Nexus also keeps a meter for every Claude Code session: requests, tokens, model and cost per request. That meter is what makes it the referee here.

```bash
nexus claude usage                         # pick a session, open its live meter (q quits)
nexus claude usage --session <id>          # open one session directly
nexus claude usage --session <id> --json   # every request as JSON (what the watchdog reads)
nexus claude usage --verbose               # one row per request, with rate details
```

The meter is a local estimate from token counts and published rates. For Fireworks spend there are two more views: the [usage dashboard](https://nexus.fireworks.ai/usage) breaks it down by model, user or API key, and your Fireworks billing page is the source of truth for the invoice.

**Good to know. Do I need a particular Nexus plan?** The race calls Kimi K3.1 Pro by name. Per the [Nexus plans page](https://docs.fireworks.ai/nexus/plans), direct access to open models is part of Enterprise; Pro and Team route through Nexus Auto instead. Check `nexus claude status` before you spend anything.

## **How do you keep the race fair?**

Every rule below exists because something could tilt the result.

**One harness, one variable.** Both sides run `claude -p` with the same flags, the same tools (Bash, Read, Edit, Write, WebFetch, WebSearch, Agent) and the same files. Only `--model` changes.

**Nothing from anyone's laptop leaks in.** `--strict-mcp-config` with an empty config removes MCP servers. `--disable-slash-commands` removes skills. Workspaces live in `~/gta-race-runs/`, outside the repo. Claude Code's own init event confirms it for each session: `mcp_servers: []`, `slash_commands: []`.

**No peeking at the other side.** Both workspaces sit in the same race folder, and both models have Bash, so a model could `cat` its rival's code. Every session, builder and critic, runs under a macOS sandbox profile. A model can read and write only its own workspace. The other model's game, the race logs, earlier races, this repo and other sessions' transcripts all return "Operation not permitted". API keys are stripped from its environment too.

**Same settings, too.** Each side gets one Claude Code settings file, identical except the model ID. Every model slot Claude Code might use, including background tasks and subagents, points at that side's own model, and no subagent can ask for another. Reasoning effort and the context size where it compacts are pinned to the same values. The watchdog still checks every request's model on every poll.

**Stopping mid-sentence doesn't end a turn.** In the dry runs, a broken connection left Kimi's turns ending on "I'm adding browser checks now…" with nothing done. Now a Stop hook catches a turn that ends on a promise, or on a game that doesn't build, and sends the model back to work with one fixed line. A turn lost to a cut-off stream is retried instead of counted.

**One playtester, same for both.** Each model can call one read-only `playtester` subagent that builds and plays the game and reports what's broken. Research on multi-agent coding found splitting a build across planner, coder and art agents hurts; a checker with fresh eyes is the one role that helps.

**One referee for money.** Every 15 seconds, the watchdog reads `nexus claude usage --json`. That gives cost at list price, subagents included, plus every model that answered. If cost reaches the budget, the turn is killed. If a foreign model appears, the run stops with `leak`. If Nexus stops answering for three minutes, the run stops with `meter_down`, because the budget can't be enforced without a reading.

**No hanging forever.** In a dry run, Kimi started `npm run preview`, a web server that never exits, as a foreground command, and sat blocked for 35 minutes. Now a turn with no output and no new spend for 10 minutes is cut short as `stalled`, and the critic reviews wherever it got to. After every turn, any server either model left running in its workspace is stopped.

**Network hiccups don't end a race.** In the first primitives dry run, the stream from the API stopped arriving 12 minutes into Kimi's build. Claude Code gave up after about six minutes of silence, and the harness, which then treated any error as fatal, ended Kimi's run at $0.41. Now a provider API error resumes the same session, up to three times per run. Every retry is logged, so reliability is reported rather than hidden.

**A clear finish line.** A run ends when the budget is spent, a leak is caught, the meter goes dark, the race is stopped (Ctrl-C or `buildoff stop`), or the process crashes. Nothing else.

**Keep it honest.** An earlier version also ended a run when the model's own critic called it Tier 4 and two harness checks agreed (the city moves, night looks different). In a $25 test run, Kimi's critic gave Tier 4 after one turn while still listing bugs, and the checks only prove that pixels move. A critic made from the same model is a coach, not a referee. So now every run spends its whole budget, and the score comes from `scoring/checklist.md`: pass/fail items per tier, each counted only when seen working in the final build, plus blind pairwise judging. We locked it (git tag `scoring-v2`, after v1 for the first $100 race) before the race it scores, so the rubric couldn't be picked after seeing who won.

There's no nudge limit. In the $25 dry runs, both models called their games done at $5–11, far short of the top tier. Now each model gets its own critic: after every turn, a fresh session of the same model, with no memory of building it, plays the game, compares it with the brief and writes the builder's next instructions. Both sides get the same setup, so the critic's quality is part of what's measured.

**Each critic starts from the last one's route.** In the first $100 race, Kimi's critics flipped between Tier 2 and Tier 4 from one round to the next. The game mostly wasn't breaking. Each fresh critic had to script its way through a long mission chain with timed key presses, and when it missed a turn and never reached a mission, it called the tier unproven. The harness's own Tier 4 check also misfired, calling the city "frozen" whenever the camera at spawn showed no traffic. Now each critic gets the last review's tier and the exact steps it used, and the builder keeps a per-tier walkthrough in `DONE.md`. The critic replays those first and still has to see everything working itself. We dropped the harness check, since the locked checklist scores Tier 4 after the race.

**Keep it honest.** Nexus is a Fireworks tool, and Kimi runs on Fireworks. The referee's numbers come from list prices with a cited source (`docs.fireworks.ai/serverless/pricing` for Kimi), and every raw transcript is kept, so anyone can recompute the spend. The budget check runs every 15 seconds, so a run can end slightly over $100. In tests the overshoot was $0.01 to $0.05.

**Keep it honest.** For now, the Claude side bills through a Claude login. For a clean "$100 at list price" comparison, Nexus needs an Anthropic API key, and that's an open item before the full race.

## **What does a race leave behind?**

Nothing records the screen. A screen recording would capture whatever else is open on the machine, so the harness keeps evidence instead:

```
~/gta-race-runs/<race-id>/
└── kimi/ and opus/
    ├── workspace/            the game
    ├── history.git/          one commit per turn, out of the model's reach
    ├── logs/turn-NNN.jsonl   builder transcript, each line {"t": seconds, "event": ...}
    ├── logs/critic-NNN.jsonl the critic's review session after each turn
    ├── logs/reviews.jsonl    every verdict: tier reached, route, notes, the review's cost and time
    ├── logs/cost.csv         spend at every Nexus poll
    ├── logs/turns.jsonl      per turn: build_ok, loaded, playable, errors, cost
    ├── shots/turn-NNN.png    gameplay screenshot (000 = untouched base game)
    ├── shots/critic-NNN/     every screenshot the critic took reviewing that turn
    └── result.json           stop reason, cost, first playable turn, models seen
```

Getting a real gameplay screenshot from headless Chrome took three fixes. Wait for the network to go quiet. Wait another 12 seconds, because the base game parses its models between downloads and takes about 9 seconds to load. Then click the middle of the screen with a small stub for the browser's pointer-lock API installed, because headless Chrome never grants pointer lock and "Click to Play" would never go away.

## **Step 1: Clone and install**

```bash
git clone https://github.com/harpreetsahota204/grand-theft-gpu
cd grand-theft-gpu
uv sync
uv run playwright install chromium
```

## **Step 2: Connect Nexus and check everything**

```bash
curl -fsSL https://nexus.fireworks.ai/install.sh | bash
nexus login        # opens a browser
nexus claude       # routes Claude Code to Fireworks for the Kimi side
uv run buildoff doctor
```

`doctor` prints `ok` or the fix for each prerequisite: macOS (for the sandbox), Claude Code 2.1.281+, Nexus connected, Node.js, git and Chromium.

## **Step 3: Run the smoke test**

```bash
uv run buildoff smoke
```

Both models get a one-line task: float the GPU above the player's head. Then each one's critic plays the result and writes a review. It costs a few dollars in total; at maximum reasoning effort, Opus alone can spend $2 on it.

## **Step 4: Run the race**

```bash
nohup uv run buildoff race --budget 100 --yes --race-id my-race > ~/gta-race-runs/my-race.log 2>&1 &
nohup uv run buildoff race --budget 100 --yes --pack primitives --race-id my-race-prim > ~/gta-race-runs/my-race-prim.log 2>&1 &
```

The first command is the asset race and the second is the primitives race. `--pack` picks both the seeded assets and the matching locked spec.

`--yes` is required for any budget over $2, because the race spends up to that amount *per model*. Running it detached keeps a long run from dying with your terminal.

## **Step 5: Watch it run**

A race runs for 30 minutes to hours. Everything you need to follow it is read-only and free:

```bash
uv run buildoff status                     # progress of the latest race, as JSON
uv run buildoff status my-race             # or a specific one
```

For each model, `status` reports the turns recorded, spend so far, the critic's tier after each round, why it stopped, the latest screenshot, and the exact `nexus_meter` command for its session. Paste that command to watch requests and tokens arrive live:

```bash
nexus claude usage --session <session_id from status>
```

That's also how you confirm Kimi is really working: every row names `kimi-k3p1-pro` on Fireworks, with its input, cached and output tokens and its cost. If the spend keeps climbing, the model is producing tokens.

To see what each critic said, round by round (tier, route, notes, what the review cost and where its screenshots are):

```bash
uv run buildoff reviews my-race
```

To follow along in more detail:

```bash
tail -f ~/gta-race-runs/my-race/kimi/logs/cost.csv      # spend at every 15-second poll
tail -f ~/gta-race-runs/my-race/kimi/logs/turns.jsonl   # one line per finished turn
open ~/gta-race-runs/my-race/kimi/shots/                # gameplay screenshots
git --git-dir ~/gta-race-runs/my-race/kimi/history.git log --oneline   # one commit per turn
```

On macOS, `--viewers` also opens a Terminal window per model that streams what it's doing. It's off by default, since an overnight run has nobody watching.

To end a race early, run `uv run buildoff stop` (or press Ctrl-C in the race's terminal). Both models stop within a second, and each writes its `result.json` with `aborted`.

**Good to know. Why does a turn take so long?** A turn lasts until the model stops on its own. In our $25 dry run, Opus's first turn was one 38-minute session that built the whole game. The harness only records a turn (commit, build, screenshot) when it ends, so `turns_recorded` stays at 0 while spend climbs. Then the critic plays the game, which at max effort can take another hour.

## **Step 6: Play the builds**

```bash
uv run buildoff play opus                  # latest race, Opus's latest build
uv run buildoff play kimi --race-id my-race
```

`play` serves that model's last build from `workspace/dist/` on localhost and opens it in your browser. Click to lock the mouse and start. Each game's controls are in its `DONE.md`. Ctrl-C stops the server. During a race, the build updates after every turn, so reload to see the newest one.

## **Results**

_The full $100 race hasn't run yet. This section will hold the tier each model reached, time to first playable build, total spend and output speed, the blind playtest, and the before/after screenshots._

## **Try it yourself**

* Repo: [github.com/harpreetsahota204/grand-theft-gpu](https://github.com/harpreetsahota204/grand-theft-gpu)
* For coding agents: [`AGENTS.md`](AGENTS.md)
* Nexus: [docs.fireworks.ai/nexus](https://docs.fireworks.ai/nexus) (session meter and usage: [docs.fireworks.ai/nexus/metrics](https://docs.fireworks.ai/nexus/metrics))
* Kimi K3.1 Pro on Fireworks: [app.fireworks.ai/models/fireworks/kimi-k3p1-pro](https://app.fireworks.ai/models/fireworks/kimi-k3p1-pro)
* NVIDIA USDCraft-10K: [huggingface.co/datasets/nvidia/USDCraft-10K](https://huggingface.co/datasets/nvidia/USDCraft-10K)

## **Frequently Asked Questions**

### **Why run Kimi inside Claude Code instead of its own agent?**
So the harness isn't a variable. Nexus points Claude Code at Fireworks, and both models get the same tool loop, prompts and permissions. Only `--model` differs.

### **Why not trust Claude Code's `total_cost_usd`?**
It doesn't know Kimi's prices and falls back to a default rate. In testing it reported $0.060 for a call that costs $0.030 at Kimi K3.1 Pro's list price ($2 per million input tokens, $10 per million output). `nexus claude usage --json` prices each row at the provider's list rate.

### **Can I change the prompt?**
Not for a comparable race. The game specs, `run_rules.md`, `critic.md` and `nudge.md` are frozen at git tag `prompt-v15`. Edit them for your own experiments, but tag the new version, because results across prompt versions aren't comparable.

### **Can I rebuild the assets myself?**
Yes. The code that builds the dataset lives in the dataset, under `build/`, and its card's [Recreate the assets](https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets#recreate-the-assets) section lists every step. You only need Blender for the USDCraft props. Races don't need any of it: they download the finished files at a pinned revision.

### **What license is this under?**
The harness is under the Business Source License 1.1. Non-commercial use is free, including running your own races and publishing the results. It converts to Apache 2.0 on 2040-01-22, which is 4,811 days after release, the same wait as GTA V to GTA 6. The assets keep their own CC0 and Apache 2.0 licenses.
