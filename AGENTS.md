# AGENTS.md

Instructions for AI coding agents working in this repo. Read this first.

## What this repo is

A harness that races two models, **Kimi K3.1 Pro** (on Fireworks, routed through Nexus) and **Claude Opus 5.5**, by giving each the same game spec and **$100** of inference in headless Claude Code. Each model builds *Grand Theft GPU*, a browser heist game, starting from the same three.js base game and asset pack. The harness meters spend, catches cross-model leaks, and records a commit, a build and a gameplay screenshot after every turn.

- `README.md`: how it works, for humans
- `AGENT_ONBOARDING.md`: the maintainers' log, with every decision, the reason behind it, and the problems hit. Read it before changing harness behavior.

## Ground rules

1. **Races spend real money.** `buildoff race` spends up to `--budget` *per model*, on the user's Fireworks and Anthropic accounts. **Never start a race above the smoke budget without the user's explicit OK** in this conversation. The CLI refuses budgets over $2 without `--yes`. Don't add `--yes` on your own.
2. **The prompt is locked.** `prompts/game_spec.md`, `prompts/run_rules.md` and `prompts/nudge.md` are frozen at git tag `prompt-v1`. Don't edit them. A change makes new races incomparable with earlier ones, and needs the user's OK and a new tag.
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
| `uv run buildoff race --budget N --yes` | Runs the locked prompt (`prompts/game_spec.md`) | up to $N per model |
| `uv run buildoff assets [gpu\|cars\|props\|catalog\|all] [--out DIR]` | Rebuilds `assets/` (and the catalog) from the original sources | free (props needs Blender) |
| `uv run buildoff assets <mirror\|city\|dataset>` | Build the Hugging Face asset dataset locally in `~/grand-theft-gpu-assets/` | free |
| `uv run buildoff assets publish` | Upload the dataset. **Public and outward-facing: only with the user's explicit OK** | free |
| `uv run buildoff inventory <categories\|list\|search\|show\|schema>` | Searches the asset catalog. JSON on stdout, JSON errors on stderr, deterministic. Start with `inventory schema`. | free |

Races run for a long time: 30 minutes to hours. Launch them detached so a tool timeout can't kill them partway, then follow `logs/turns.jsonl`:

```bash
nohup uv run buildoff race --budget N --yes --race-id my-race > ~/gta-race-runs/my-race.log 2>&1 &
```

## Checking a run

Outputs go to `~/gta-race-runs/<race-id>/<model>/`:
- `result.json`: the stop reason, cost (from Nexus, at list price), turns, the first playable turn, and every model seen (it must be only that side's own model)
- `logs/turns.jsonl`: per turn, whether it built and loaded, plus console errors. Turn 0 is the untouched base game.
- `shots/turn-NNN.png`: gameplay screenshots
- `workspace/`: the game the model built, as a git repo with one commit per turn

A healthy smoke run shows `declared_done`, `build_ok: true` and `loaded: true` on every turn including turn 0, and `models_seen` containing only that model.

## Code map

| Path | Role |
|---|---|
| `harness/cli.py` | The `buildoff` entry point |
| `harness/race.py` | Runs the contenders in parallel |
| `harness/runner.py` | One contender: turn loop, budget/leak watchdog, stop rules |
| `harness/seed.py` | Seeds a workspace with the base game (pinned commit) and assets |
| `harness/snapshot.py` | Per-turn git commit, Vite build and gameplay screenshot |
| `harness/meter.py` | Reads cost and models from `nexus claude usage --json` |
| `harness/viewer.py` | Live terminal view of a contender |
| `harness/doctor.py`, `harness/assets.py` | Prerequisite checks; asset rebuild |
| `harness/catalog.py`, `harness/inventory.py` | Builds `assets/catalog.json`; the `inventory` query layer |
| `harness/mirror.py`, `harness/sfcity.py`, `harness/dataset.py` | Asset dataset: pinned mirrors, the SF slice, cards and upload ([on the Hub](https://huggingface.co/datasets/harpreetsahota/grand-theft-gpu-assets)) |
| `harness/config.py` | Every constant: contenders, limits, paths, pinned base commit |
| `scripts/convert_usdcraft.py` | OpenUSD → glb converter (runs inside Blender) |
| `prompts/` | The locked game prompt, run rules, nudge, smoke spec |
| `assets/` | GPU (CC0), cars (CC0), USDCraft props (Apache 2.0); each folder keeps its license |

## Code conventions

- Google-style docstrings and full type hints on every function. Comments explain *why*.
- `uv run ruff check harness scripts` and `uv run ruff format harness scripts` must pass.
- There's no unit test suite. Verify harness changes with `buildoff smoke`, or for asset changes by rebuilding with `--out` and diffing against `assets/`.

## Known problems

- **zsh:** `$FLAGS` doesn't word-split, and a variable named `path` overwrites `$PATH`. Use bash for shell loops.
- **Claude Code misprices Kimi** (about 2x list). Always use Nexus numbers for cost, never Claude Code's `total_cost_usd`.
- **Models can start servers that never exit** (`npm run preview`, `npm run dev`). The runner kills a turn after 10 minutes with no output and no new spend (`stalled`, then a nudge), and after every turn it kills any process whose working directory is inside the workspace.
- **Asset catalog determinism:** part names are read from the glTF JSON, not from trimesh, which appends random suffixes. Rebuilding unchanged assets gives a byte-identical `assets/catalog.json`.
- **Screenshots** need a network-idle wait, a long settle, and a click with the pointer-lock shim (`snapshot.POINTER_LOCK_SHIM`). Otherwise they show a half-loaded frame or the "Click to Play" menu.
- **The base game commits a broken `node_modules`** (no execute bits, and native binaries for another OS). `seed.py` skips it and reinstalls cleanly.
