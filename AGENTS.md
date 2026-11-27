# AGENTS.md

Instructions for AI coding agents working in this repo. Read this first. Maintainers also keep `AGENT_ONBOARDING.md` (current decisions and why), a local file that isn't published: read it before changing harness behavior if you have it.

## What this repo is

A harness that races two models, **Kimi K3.1 Pro** (on Fireworks, routed through Nexus) and **Claude Opus 5.5**, on the same brief and budget in headless Claude Code. Each builds *Grand Theft GPU*, a browser heist game, from the same blank Vite + three.js starter project. After every builder turn, a critic (a fresh session of the same model) plays the game and writes the next prompt. A run ends when the budget runs out; the critic's tier never ends it. The harness sandboxes each model, meters spend through Nexus, catches cross-model leaks, and records a commit, a build and a screenshot every turn.

**Status: the race is done.** The official result is `v19-full-100usd-001` (`prompt-v19`), in `~/gta-race-runs/v19-full-100usd-001/`; `README.md` has the numbers. The two final builds are judged by blind human votes in the public arena Space (`arena/`). Don't propose or start another race unless the user asks.

`README.md` explains how a race works. `HUMANS.md` is the story version for people.

## Ground rules

1. **Races spend real money.** `buildoff race` spends up to `--budget` *per model* on the user's Fireworks and Anthropic accounts. **Never start a race without the user's explicit OK in this conversation.** The CLI refuses budgets over $2 without `--yes`; don't add `--yes` on your own. `buildoff smoke` (about $2–4) is the only paid check you may run unasked, and only to verify a harness change.
2. **The prompts are locked** at git tag `prompt-v19`: `prompts/game_spec.md`, `game_spec_primitives.md`, `run_rules.md`, `critic.md` and `nudge.md` (the template that wraps the critic's notes). A change needs the user's OK and a new tag, because results across prompt versions aren't comparable.
3. **Fairness is the product.** Both sides get identical flags, tools, files, settings and rules; only the model ID differs (in `--model` and the per-side settings files; `tests/test_session.py` checks this). Never change one side alone.
4. **Don't read credentials.** Never open `~/.claude/settings.json` or other key files. Use `nexus claude status` to check routing.
5. **Don't use `--dangerously-skip-permissions` or `claude --bare`.** The harness pre-approves tools with `--allowed-tools`, and `--bare` breaks Nexus auth.
6. **Some steps need a human.** `nexus login` opens a browser, so ask the user to run it (`! nexus login`). Publishing to the asset dataset is public: only with the user's OK.

## Setup

```bash
uv sync                                  # Python 3.12 env plus the `buildoff` CLI
uv run playwright install chromium       # headless browser for screenshots
uv run buildoff doctor                   # every line should say ok
```

Requires macOS (`sandbox-exec`), Claude Code 2.1.281+, the Nexus CLI logged in and connected (`nexus login`, then `nexus claude`), Node.js and git. Rebuilding the asset dataset is separate: its code and instructions live in the dataset, under `build/`.

## Commands

| Command | What it does | Cost |
|---|---|---|
| `uv run pytest` | Local tests: critic parsing (scores, untested, shots), last round's shots staged for the critic, review trace, meter, sandbox, Stop hook, settings parity, evidence, asset lookup, blind arena | free, ~2 s |
| `uv run buildoff doctor` | Checks prerequisites | free |
| `uv run buildoff smoke` | End to end: both models add a floating GPU, then one critic review each | ~$2–4 |
| `uv run buildoff race --budget N --yes [--pack full\|primitives] [--viewers]` | A race on that pack's locked spec (races use `full`; `primitives` is kept but unused); `--viewers` opens a live Terminal window per model | up to $N per model |
| `uv run buildoff status [race-id]` | Progress as JSON, with the critic's tier and look/feel scores per round (latest race by default) | free |
| `uv run buildoff reviews [race-id]` | Every critic round: tier, scores, untested steps, route, fixed notes, notes, cost, time, screenshots | free |
| `uv run buildoff play <kimi\|opus> [--race-id ID]` | Serves a contender's latest build on localhost | free |
| `uv run buildoff stop [race-id]` | Aborts a race cleanly and kills any orphaned session | free |
| `uv run buildoff fetch <id ...> \| --core \| --pattern G` | Downloads assets from the pinned Hugging Face revision | free |
| `uv run python arena/prepare.py --race-id ID` | Packages a race's two final builds into opaque folders for the blind arena Space and scans them for identity leaks (`arena/README.md` covers running and deploying) | free |
| `node <workspace>/tools/assets.mjs search police car` | Searches the catalog with the models' own tool (in any full-pack race workspace) | free |

Races take hours. Launch them detached and check in with `status` and `reviews`. The harness keeps the Mac awake by itself (keep it plugged in, lid open):

```bash
nohup uv run buildoff race --budget N --yes --race-id my-race > ~/gta-race-runs/my-race.log 2>&1 &
```

## Checking a run

Outputs go to `~/gta-race-runs/<race-id>/<model>/`:
- `result.json`: the stop reason (`budget`, `declared_done` in smoke tests, or a safety stop: `leak`, `meter_down`, `aborted`, `error`), total cost from Nexus (builder and critics), turns, reviews, last tier, model time, first playable turn, and every model seen (must be only that side's own)
- `logs/turns.jsonl`: per turn, whether it built, loaded and was `playable`, plus errors. Turn 0 is the untouched starter scene.
- `logs/reviews.jsonl`: each critic verdict (tier, look/feel scores, untested steps, route, fixed note ids, notes as ledger entries with id, status, brief line and shots, that review's cost and time); `buildoff reviews` lists them per round
- `logs/turn-NNN.jsonl`, `logs/critic-NNN.jsonl`: timestamped transcripts
- `logs/events.jsonl`: leaks, stalls, a dead meter, aborts, retries, harness errors with traceback
- `shots/turn-NNN.png`, `shots/critic-NNN/` (the critic's own screenshots that round), `workspace/`, `history.git/` (`git --git-dir=history.git log`), `toolkit/` (what ran inside the sandbox)

A healthy smoke run shows `declared_done`, `playable: true` on every turn, a parsed review in `reviews.jsonl`, and only that side's model in `models_seen`. `smoke` and `race` exit 1 if a side ended on `error`, `leak`, `meter_down` or `aborted`.

## Code map

| Path | Role |
|---|---|
| `harness/cli.py` | The `buildoff` entry point |
| `harness/race.py` | Runs both contenders in parallel; abort handling, keep-awake, `stop` |
| `harness/runner.py` | One contender: build turn → evidence → critic review (given the last review's route and notes, the ledger) → next prompt; the spend/leak/stall watchdog |
| `harness/session.py`, `harness/stop_hook.py` | Per-side Claude Code settings (model pins, effort, compaction), the Stop hook, the playtester subagent |
| `harness/sandbox.py` | Per-side `sandbox-exec` profiles (builder; read-only critic) and the scrubbed environment |
| `harness/seed.py` | Seeds a workspace: the starter project (`workspace_tools/seed/`), assets, tools, `npm ci` |
| `harness/snapshot.py` | Per-turn commit, Vite build and gameplay screenshot |
| `harness/meter.py` | Reads cost and models from `nexus claude usage --json` |
| `harness/status.py`, `harness/viewer.py` | `status`, `reviews` and `play`; the optional live terminal viewer |
| `harness/shot_tool.py`, `harness/workspace_tools/assets.mjs` | The models' `tools/screenshot` and asset search tool |
| `harness/config.py` | Every constant: contenders, limits, paths, pinned commits and revisions |
| `harness/fetch.py`, `assets/catalog.json` | Downloads assets at the pinned dataset revision; the index the models search with `tools/assets.mjs` |
| `scoring/checklist.md` | A pass/fail rubric locked before the race (tag `scoring-v2`), never shown to the models. The arena's four vote questions come from it; the race was judged by the arena vote, not the checklist |
| `prompts/` | The locked game specs, run rules, critic prompt and nudge template; `smoke_spec.md` |
| `arena/` | The public blind play-and-vote Space: `app.py` (FastAPI routes), `blind.py` (signed A/B tokens, asset shim, input and snapshot logger), `storage.py` (votes, play time, input logs, snapshots, Hub sync), `prepare.py` (packages builds), `export_coco4gui.py` (snapshots + inputs → COCO4GUI) |
| `tests/` | The local test suite |

## Code conventions

- Google-style docstrings and full type hints on every function; comments explain *why*.
- `uv run ruff check harness arena tests`, `uv run ruff format harness arena tests` and `uv run pytest` must pass.
- Verify harness changes with the tests first, then `buildoff smoke`.
- Keep the docs current in the same change. If you have `AGENT_ONBOARDING.md`, it describes the present: rewrite its rows, don't append history.

## Known pitfalls

- **zsh:** `$VAR` doesn't word-split, unmatched globs abort the command, and a variable named `path` overwrites `$PATH`. Use `bash -c` for loops.
- **Claude Code misprices Kimi** (about 2x list). Use Nexus numbers, never Claude Code's `total_cost_usd`.
- **Anything that runs inside the sandbox** (the Stop hook, `tools/screenshot`) must be listed in `seed.TOOLKIT_MODULES`; the sandbox can't read this repo.
- **Screenshots render on the GPU** (`snapshot.CHROMIUM_ARGS`, ANGLE Metal). Don't switch back to SwiftShader: it ran race builds at ~10 fps, so scripted key holds stopped being repeatable.
- **Closing the lid sleeps the Mac** despite `caffeinate`, and a sleeping Mac breaks the models' API streams.
- **Don't `kill -9` the harness:** `claude` runs in its own session and would keep spending. Use Ctrl-C, `kill`, or `buildoff stop` (which also kills orphans).
