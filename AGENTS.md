# AGENTS.md

Instructions for AI coding agents working in this repo. Read this first, then `AGENT_ONBOARDING.md` (current decisions and why) before changing harness behavior.

## What this repo is

A harness that races two models, **Kimi K3.1 Pro** (on Fireworks, routed through Nexus) and **Claude Opus 5.5**, on the same brief and budget in headless Claude Code. Each builds *Grand Theft GPU*, a browser heist game, from the same three.js base game. After every builder turn, a critic (a fresh session of the same model) plays the game and writes the next prompt. A run ends when Tier 4 is verified or the budget runs out. The harness sandboxes each model, meters spend through Nexus, catches cross-model leaks, and records a commit, a build and a screenshot every turn.

`README.md` explains how a race works. `HUMANS.md` is the story version for people.

## Ground rules

1. **Races spend real money.** `buildoff race` spends up to `--budget` *per model* on the user's Fireworks and Anthropic accounts. **Never start a race without the user's explicit OK in this conversation.** The CLI refuses budgets over $2 without `--yes`; don't add `--yes` on your own. `buildoff smoke` (about $2–4) is the only paid check you may run unasked, and only to verify a harness change.
2. **The prompts are locked** at git tag `prompt-v7`: `prompts/game_spec.md`, `game_spec_primitives.md`, `run_rules.md`, `critic.md` and `nudge.md` (the template that wraps the critic's notes). A change needs the user's OK and a new tag, because results across prompt versions aren't comparable.
3. **Fairness is the product.** Both sides get identical flags, tools, files, settings and rules; only the model ID differs (in `--model` and the per-side settings files; `tests/test_session.py` checks this). Never change one side alone.
4. **Don't read credentials.** Never open `~/.claude/settings.json` or other key files. Use `nexus claude status` to check routing.
5. **Don't use `--dangerously-skip-permissions` or `claude --bare`.** The harness pre-approves tools with `--allowed-tools`, and `--bare` breaks Nexus auth.
6. **Some steps need a human.** `nexus login` opens a browser, so ask the user to run it (`! nexus login`). `buildoff assets publish` is public: only with the user's OK.

## Setup

```bash
uv sync                                  # Python 3.12 env plus the `buildoff` CLI
uv run playwright install chromium       # headless browser for screenshots
uv run buildoff doctor                   # every line should say ok
```

Requires macOS (`sandbox-exec`), Claude Code 2.1.281+, the Nexus CLI logged in and connected (`nexus login`, then `nexus claude`), Node.js and git. Blender and the `hf` CLI are only for rebuilding assets.

## Commands

| Command | What it does | Cost |
|---|---|---|
| `uv run pytest` | Local tests: critic parsing, meter, sandbox, Stop hook, settings parity, checks, evidence | free, ~2 s |
| `uv run buildoff doctor` | Checks prerequisites | free |
| `uv run buildoff smoke` | End to end: both models add a floating GPU, then one critic review each | ~$2–4 |
| `uv run buildoff race --budget N --yes [--pack full\|primitives]` | A race on that pack's locked spec | up to $N per model |
| `uv run buildoff status [race-id]` | Progress as JSON (latest race by default) | free |
| `uv run buildoff play <kimi\|opus> [--race-id ID]` | Serves a contender's latest build on localhost | free |
| `uv run buildoff stop [race-id]` | Aborts a race cleanly and kills any orphaned session | free |
| `uv run buildoff inventory <schema\|categories\|list\|search\|show>` | Searches the asset catalog (JSON out) | free |
| `uv run buildoff fetch <id ...> \| --core \| --pattern G` | Downloads assets from the pinned Hugging Face revision | free |
| `uv run buildoff assets <gpu\|props\|catalog\|mirror\|city\|textures\|media\|dataset\|publish>` | Rebuilds or stages assets; `publish` is public (user's OK only) | free |

Races take hours. Launch them detached and check in with `status`. The harness keeps the Mac awake by itself (keep it plugged in, lid open):

```bash
nohup uv run buildoff race --budget N --yes --race-id my-race > ~/gta-race-runs/my-race.log 2>&1 &
```

## Checking a run

Outputs go to `~/gta-race-runs/<race-id>/<model>/`:
- `result.json`: the stop reason (`tier4`, `budget`, or a safety stop: `leak`, `meter_down`, `aborted`, `error`), total cost from Nexus (builder and critics), turns, reviews, last tier, model time, first playable turn, and every model seen (must be only that side's own)
- `logs/turns.jsonl`: per turn, whether it built, loaded and was `playable`, plus errors. Turn 0 is the untouched base game.
- `logs/reviews.jsonl`: each critic verdict (tier, Tier 4 claim, notes) and any Tier 4 check result
- `logs/turn-NNN.jsonl`, `logs/critic-NNN.jsonl`: timestamped transcripts
- `logs/events.jsonl`: leaks, stalls, a dead meter, aborts, retries, harness errors with traceback
- `shots/turn-NNN.png`, `workspace/`, `history.git/` (`git --git-dir=history.git log`), `toolkit/` (what ran inside the sandbox)

A healthy smoke run shows `declared_done`, `playable: true` on every turn, a parsed review in `reviews.jsonl`, and only that side's model in `models_seen`. `smoke` and `race` exit 1 if a side ended on `error`, `leak`, `meter_down` or `aborted`.

## Code map

| Path | Role |
|---|---|
| `harness/cli.py` | The `buildoff` entry point |
| `harness/race.py` | Runs both contenders in parallel; abort handling, keep-awake, `stop` |
| `harness/runner.py` | One contender: build turn → evidence → critic review → Tier 4 check → next prompt; the spend/leak/stall watchdog |
| `harness/checks.py` | The harness's own Tier 4 checks |
| `harness/session.py`, `harness/stop_hook.py` | Per-side Claude Code settings (model pins, effort, compaction), the Stop hook, the playtester subagent |
| `harness/sandbox.py` | Per-side `sandbox-exec` profiles (builder; read-only critic) and the scrubbed environment |
| `harness/seed.py` | Seeds a workspace: base game at a pinned commit, assets, tools, `npm ci` |
| `harness/snapshot.py` | Per-turn commit, Vite build and gameplay screenshot |
| `harness/meter.py` | Reads cost and models from `nexus claude usage --json` |
| `harness/status.py`, `harness/viewer.py` | `status` and `play`; the live terminal viewer |
| `harness/shot_tool.py`, `harness/workspace_tools/assets.mjs` | The models' `tools/screenshot` and asset search tool |
| `harness/config.py` | Every constant: contenders, limits, paths, pinned commits and revisions |
| `harness/catalog.py`, `inventory.py`, `fetch.py`, `mirror.py`, `sfcity.py`, `textures.py`, `media.py`, `dataset.py`, `assets.py` | The asset dataset: build, index, search, fetch, publish |
| `prompts/` | The locked game specs, run rules, critic prompt and nudge template; `smoke_spec.md` |
| `tests/` | The local test suite |

## Code conventions

- Google-style docstrings and full type hints on every function; comments explain *why*.
- `uv run ruff check harness scripts tests`, `uv run ruff format harness scripts tests` and `uv run pytest` must pass.
- Verify harness changes with the tests first, then `buildoff smoke`. For asset changes, rebuild with `--out` and diff.
- Keep the docs current in the same change. `AGENT_ONBOARDING.md` describes the present: rewrite its rows, don't append history.

## Known pitfalls

- **zsh:** `$VAR` doesn't word-split, unmatched globs abort the command, and a variable named `path` overwrites `$PATH`. Use `bash -c` for loops.
- **Claude Code misprices Kimi** (about 2x list). Use Nexus numbers, never Claude Code's `total_cost_usd`.
- **Anything that runs inside the sandbox** (the Stop hook, `tools/screenshot`) must be listed in `seed.TOOLKIT_MODULES`; the sandbox can't read this repo.
- **Closing the lid sleeps the Mac** despite `caffeinate`, and a sleeping Mac breaks the models' API streams.
- **Don't `kill -9` the harness:** `claude` runs in its own session and would keep spending. Use Ctrl-C, `kill`, or `buildoff stop` (which also kills orphans).
- More gotchas, with reasons, are in `AGENT_ONBOARDING.md`.
