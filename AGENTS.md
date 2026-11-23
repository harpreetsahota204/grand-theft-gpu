# AGENTS.md

Instructions for AI coding agents working in this repo. Read this first.

## What this repo is

A harness that races two models, **Kimi K3.1 Pro** (on Fireworks, routed through Nexus) and **Claude Opus 5.5**, by giving each the same game spec and **$100** of inference in headless Claude Code. Each model builds *Grand Theft GPU*, a browser heist game, starting from the same three.js base game and asset pack. The harness meters spend, catches cross-model leaks, and records a commit, a build and a gameplay screenshot after every turn.

- `README.md`: how it works, for humans
- `AGENT_ONBOARDING.md`: the maintainers' log, with every decision, the reason behind it, and the problems hit. Read it before changing harness behavior.

## Ground rules

1. **Races spend real money.** `buildoff race` spends up to `--budget` *per model*, on the user's Fireworks and Anthropic accounts. **Never start a race above the smoke budget without the user's explicit OK** in this conversation. The CLI refuses budgets over $2 without `--yes`. Don't add `--yes` on your own.
2. **The prompts are locked.** `prompts/game_spec.md` (full asset pack), `prompts/game_spec_primitives.md` (primitives race), `prompts/run_rules.md` and `prompts/nudge.md` are frozen at git tag `prompt-v5` (the current version). Don't edit them. A change makes new races incomparable with earlier ones, and needs the user's OK and a new tag.
3. **Fairness is the product.** Both sides must get identical flags, tools, files and rules; only `--model` differs. Don't change one side's setup alone.
4. **Don't read credentials.** Never open `~/.claude/settings.json` or other key files. Use `nexus claude status` to check routing.
5. **Don't use `--dangerously-skip-permissions` or `claude --bare`.** The harness pre-approves tools with `--allowed-tools`. `--bare` breaks Nexus auth.
6. **Some steps need a human.** `nexus login` opens a browser; ask the user to run it (in Claude Code: `! nexus login`).

## Setup

```bash
uv sync                                  # Python 3.12 env plus the `buildoff` CLI
uv run playwright install chromium       # headless browser for screenshots
uv run buildoff doctor                   # every line should say ok
```

If `doctor` reports missing items, each line says how to fix it. The required items: Claude Code 2.1.242+, Nexus CLI logged in and connected (`nexus login` then `nexus claude`), Node.js and git. Blender and the `hf` CLI are only needed to rebuild assets.

## Commands

| Command | What it does | Cost |
|---|---|---|
| `uv run buildoff doctor` | Checks prerequisites | free |
| `uv run buildoff smoke` | End-to-end check: both models add a floating GPU to the base game | about $0.30 total |
| `uv run buildoff race --budget N --yes [--pack full\|primitives]` | Runs the locked prompt for that pack (`game_spec.md` with the full asset pack, or `game_spec_primitives.md` with only the GPU) | up to $N per model |
| `uv run buildoff status [race-id]` | Race progress as JSON: turns, spend, stop reason, Nexus session, latest screenshot (latest race by default) | free |
| `uv run buildoff play <kimi\|opus> [--race-id ID] [--no-open]` | Serves a contender's latest build on localhost and opens the browser (blocks until Ctrl-C) | free |
| `uv run buildoff stop [race-id]` | Aborts a running race: SIGTERMs the harness (each side stops as `aborted` and writes `result.json`), then kills any turn still running | free |
| `uv run buildoff assets [gpu\|cars\|props\|catalog\|all] [--out DIR]` | Rebuilds `assets/` (and the catalog) from the original sources | free (props needs Blender) |
| `uv run buildoff fetch <id ...> [--tiers] \| --core \| --pattern G` | Download assets from the Hugging Face dataset at the pinned revision. JSON summary. | free |
| `uv run buildoff assets <mirror\|city\|textures\|media\|dataset>` | Build the Hugging Face asset dataset locally in `~/grand-theft-gpu-assets/` (third-party mirrors, the SF city, skies + PBR textures, sounds + sprites + fonts, then cards and attribution) | free |
| `uv run buildoff assets publish` | Upload the dataset. **Public and outward-facing: only with the user's explicit OK** | free |
| `uv run buildoff inventory <categories\|list\|search\|show\|schema>` | Searches the asset catalog. JSON on stdout, JSON errors on stderr, deterministic. Start with `inventory schema`. | free |

Races run for a long time: 30 minutes to hours. Launch them detached so a tool timeout can't kill them partway, then check progress with `uv run buildoff status` (or follow `logs/turns.jsonl`). `caffeinate -i` stops the Mac from idle-sleeping, and the lid must stay open: a sleeping Mac pauses the race (the 2026-11-21 dry runs crept through the night in maintenance wakes):

```bash
nohup caffeinate -i uv run buildoff race --budget N --yes --race-id my-race > ~/gta-race-runs/my-race.log 2>&1 &
```

## Checking a run

Outputs go to `~/gta-race-runs/<race-id>/<model>/`:
- `result.json`: the stop reason, cost (from Nexus, at list price), turns, model time (`model_seconds`, the race clock) and wall time, the first playable turn, and every model seen (it must be only that side's own model)
- `logs/turns.jsonl`: per turn, whether it built, loaded and was `playable` (rendered with no uncaught exception), plus page and console errors. Turn 0 is the untouched base game.
- `logs/events.jsonl`: leaks, stalls, a dead meter, aborts, API retries and harness errors (with traceback)
- `shots/turn-NNN.png`: gameplay screenshots
- `workspace/`: the game the model built
- `history.git/`: one commit per turn of `workspace/`, kept outside it so the model can't rewrite it. Read it with `git --git-dir=history.git log` (`buildoff status` prints the command)

A healthy smoke run shows `declared_done`, `build_ok: true` and `playable: true` on every turn including turn 0, and `models_seen` containing only that model. `buildoff smoke` and `buildoff race` exit 1 if either side ended on `error`, `leak`, `meter_down` or `aborted`.

## Code map

| Path | Role |
|---|---|
| `harness/cli.py` | The `buildoff` entry point |
| `harness/race.py` | Runs the contenders in parallel |
| `harness/runner.py` | One contender: turn loop, budget/leak/meter watchdog, stop rules, abort and cleanup |
| `harness/sandbox.py` | Per-contender isolation: the `sandbox-exec` profile and the scrubbed environment |
| `harness/seed.py` | Seeds a workspace with the base game (pinned commit) and assets |
| `harness/snapshot.py` | Per-turn git commit, Vite build and gameplay screenshot |
| `harness/meter.py` | Reads cost and models from `nexus claude usage --json` |
| `harness/status.py` | `buildoff status` / `buildoff play`: race progress JSON, serve a build locally |
| `harness/viewer.py` | Live terminal view of a contender |
| `harness/doctor.py`, `harness/assets.py` | Prerequisite checks; asset rebuild |
| `harness/catalog.py`, `harness/inventory.py` | Builds `assets/catalog.json`; the `inventory` query layer |
| `harness/mirror.py`, `harness/sfcity.py`, `harness/textures.py`, `harness/media.py`, `harness/dataset.py` | Asset dataset: pinned mirrors, the SF slice, skies and textures, sounds/sprites/fonts, cards and upload ([on the Hub](https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets)) |
| `harness/config.py` | Every constant: contenders, limits, paths, pinned base commit |
| `scripts/convert_usdcraft.py` | OpenUSD → glb converter (runs inside Blender) |
| `prompts/` | The locked game prompt, run rules, nudge, smoke spec |
| `assets/catalog.json` | Index of all 1,302 assets in the [Hugging Face dataset](https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets) (the assets themselves aren't in git) |
| `harness/shot_tool.py` | The models' `tools/screenshot`: build + render the game to a PNG (both models can read images) |
| `harness/fetch.py`, `harness/workspace_tools/assets.mjs` | Fetching from the dataset; the racing models' own search + fetch tool |

## Code conventions

- Google-style docstrings and full type hints on every function. Comments explain *why*.
- `uv run ruff check harness scripts` and `uv run ruff format harness scripts` must pass.
- `uv run pytest` must pass (`tests/`: stop rules, meter, sandbox enforcement on the real `sandbox-exec`, evidence history, zip-slip, search parity between `assets.mjs` and `inventory`). It's free and takes seconds. Then verify end to end with `buildoff smoke`, or for asset changes by rebuilding with `--out` and diffing against `assets/`.

## Known problems

- **zsh:** `$FLAGS` doesn't word-split, and a variable named `path` overwrites `$PATH`. Use bash for shell loops.
- **Claude Code misprices Kimi** (about 2x list). Always use Nexus numbers for cost, never Claude Code's `total_cost_usd`.
- **Models can start servers that never exit** (`npm run preview`, `npm run dev`). The runner kills a turn after 10 minutes with no output and no new spend (`stalled`, then a nudge), and after every turn it kills the turn's whole process group plus any process whose working directory is inside the workspace.
- **Stopping a race:** Ctrl-C, `kill <harness pid>` or `buildoff stop` all abort cleanly. Don't `kill -9` the harness: `claude` runs in its own session and would keep spending. If that happens anyway, `buildoff stop` kills the orphaned turn via `logs/claude.pgid`.
- **Isolation is macOS `sandbox-exec`** (`harness/sandbox.py`). A model can read and write only its own workspace. It can't read the other contender, the race logs, earlier races, this repo, or other sessions' transcripts. Its environment is scrubbed to `config.ENV_ALLOWLIST`. It can still read `~/.claude/settings.json`, because Claude Code needs it for Nexus routing. If you add a tool the models run, it must work inside that profile (see `seed.write_toolkit`).
- **The meter fails closed:** if Nexus gives no reading for `METER_BLIND_LIMIT_S` (3 min) during a turn, the run stops as `meter_down`.
- **Asset catalog determinism:** part names are read from the glTF JSON, not from trimesh, which appends random suffixes. Rebuilding unchanged assets gives a byte-identical `assets/catalog.json`.
- **Screenshots** need a network-idle wait, a long settle, and a click with the pointer-lock shim (`snapshot.POINTER_LOCK_SHIM`). Otherwise they show a half-loaded frame or the "Click to Play" menu.
- **The base game commits a broken `node_modules`** (no execute bits, and native binaries for another OS). `seed.py` skips it and reinstalls cleanly.
