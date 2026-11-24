# Agent onboarding

The current state of the project and the reasons behind it. `AGENTS.md` says how to work in the repo; `README.md` says how a race works. This file says **why it's built this way and what to watch out for**. It describes the present only: history lives in git (`git log`, tags `prompt-v*`).

**Keep it current.** When a decision changes, rewrite its row; don't append. Delete what stops being true.

_Last updated: 2026-11-23_

## The project

A Fireworks DevRel piece. Kimi K3.1 Pro (open model, on Fireworks) and Claude Opus 5.5 each get up to $100 of inference and the same brief, and each builds a browser GTA-style heist game, **Grand Theft GPU**, alone in headless Claude Code. The results are scored on a four-tier ladder (labelled GTA 1→4 in the video) and cut into a split-screen race video. Nexus (the Fireworks CLI that routes Claude Code to Fireworks models) is the plumbing and the spend referee: the tool in the story, never the topic. A later Part 2 trains Kimi with RL to play its own game.

Two races run side by side and get compared: **full assets** (`--pack full`) and **primitives** (`--pack primitives`: only the GPU model; everything else made in code).

The internal program brief is `PROGRAM_BRIEF.md` (local, gitignored). The user's working style is in `CLAUDE.local.md` (gitignored, loaded automatically).

## The game, as the prompt fixes it

The locked prompts (`prompts/`, tag `prompt-v7`) fix only the world, the gameplay and the rules. Everything else (story, missions, characters, visual style, how far past the minimum to go) is the model's.

- **World:** San Silicon, a parody of San Francisco. The cast is tech-Twitter archetypes (VCs, hype beasts, grifters, anon accounts), never real people. Brands are parodies.
- **Must-haves:** steal a GPU, drive a car (in, drive, out), talk to an archetype in their own voice, get chased with heat that rises and falls.
- **Tiers:** T1 steal a GPU; T2 car escape with heat; T3 multi-mission story with talking archetypes; T4 a living city (traffic, robotaxis, pedestrians, day and night). The prompt calls them Small-time → Kingpin; "GTA 1–4" is only for the video.
- **Hard rules:** no real people or brands, no slurs or punching down, no real-world theft or hacking how-tos, cartoonish violence only.
- **The models know** they have about $100 and that a critic reviews each turn. They aren't told they're racing another model.

## Decisions in force, and why

| Decision | Why |
|---|---|
| Both models run **in headless Claude Code, in parallel, on the user's Mac** | One harness, one time window, the same API conditions. Moonshot reports Kimi K3.1 Pro's coding scores in Claude Code, so it isn't a foreign harness for Kimi. |
| **Only the model ID differs** between sides: same flags, tools, files and settings (`harness/session.py`, checked by `tests/test_session.py`) | Fairness is the product. |
| Models **pinned by full ID** (`kimi-k3p1-pro`, `claude-opus-5-5`); every model tier and subagent pinned to the side's own model (`CLAUDE_CODE_SUBAGENT_MODEL` + `_FORCE`, `ANTHROPIC_DEFAULT_*_MODEL`) | Aliases can move mid-race. The subagent env var alone ranks below a spawn call's model and an agent definition's, and some built-in subagents default to Haiku. |
| **Nexus is the source of truth for spend** (`nexus claude usage --json`: list price, subagents included), polled every 15 s; the budget and leak check cover all of a contender's sessions (builder and critics) | Claude Code misprices Kimi (about 2x list). Any model other than the contender's in the usage rows stops the run as `leak`. |
| **Critic loop, no nudge cap.** After every builder turn, a fresh session of the same model plays the game read-only and writes the next prompt (`prompts/critic.md`, `prompts/nudge.md`) | With a fixed nudge and a 3-nudge cap, every dry run stopped at $5–11, far from Tier 4. The user wants each model to keep building until Tier 4, with its own critic deciding what to improve. |
| **A run ends on Tier 4 only if the critic says so and `harness/checks.py` agrees** (playable; the city moves with no input; the critic's day and night shots differ). Otherwise only the budget or a safety stop ends it | Models grade their own work too kindly. The checks are necessary, not sufficient: they catch a frozen city or no night, not a poor one. |
| **Same effort (`max`) and compaction point (1M tokens)** on both sides | Unpinned defaults could differ by provider. Moonshot evaluates K3.1 at max effort. |
| **Stop hook** on builder turns (`harness/stop_hook.py`): blocks a stop when the last message announces work or the game doesn't build | Dry-run turns ended on "I'm adding checks now…" with nothing done. Its reason is the nudge template's fixed last line, so it adds no new instruction. |
| **One read-only `playtester` subagent** offered to both builders | Research (MAST, Cognition, Anthropic) found planner/coder/art teams hurt single-codebase builds; a fresh-eyes checker is the one role with evidence behind it. |
| **A macOS `sandbox-exec` profile per contender** (`harness/sandbox.py`), environment scrubbed to `ENV_ALLOWLIST`; the critic's profile is read-only except build output and its own shots | Both workspaces sit side by side and both models have Bash. A model can't read the other side, the logs, earlier races, this repo or other sessions' transcripts, and can't plant `.claude/` config. `~/.claude/settings.json` stays readable because Claude Code needs it for Nexus. |
| **Fail closed.** SIGINT/SIGTERM abort both sides within 1 s; a crash still kills the running session and writes `result.json`; `buildoff stop` kills orphans; a meter blind for 3 min stops the run (`meter_down`) | `claude` runs in its own session, so a dead harness would otherwise leave it spending with no budget check. |
| **Evidence:** per-turn commits in `history.git` outside the workspace, a Vite build and a gameplay screenshot every turn, every critic's own screenshots (`shots/critic-NNN/`), timestamped transcripts. **No screen recording** | The model can't rewrite its history. A screen recording once captured the user's other windows, so the video is rendered from the logs instead. |
| **Playable** = built, loaded, rendered, no uncaught exception (console errors are logged but don't fail it). The race clock counts model time only | 404s and logged warnings wrongly failed turns; counting harness build time penalised models that take more turns. |
| **Provider API errors and cut-off streams are retried** (up to 3 per run) | Infrastructure, not the model. |
| **The harness keeps the Mac awake** (`caffeinate -ims` for its whole run) | A sleeping Mac broke streams on both sides (up to 32 retries per turn) and voided the 2026-11-21 dry runs. Closing the lid still sleeps it. |
| **Assets live in the Hugging Face dataset** `harpreetsahota/grand-theft-gpu-assets`, pinned by `HF_ASSETS_REVISION`. The repo tracks only `assets/catalog.json`. Every workspace is seeded with the full web tier (~650 MB) | Identical toolboxes for both sides; size costs seconds, not money or fairness. Fetching extras mid-race spends the model's own budget. |
| **Asset choices:** adults only, no religious dress or swimwear; vehicles and trees set to real size and one heading; real brand names on textures are fine (the user's call) | So no model casts a real group as the villains of a satire. The upstream converter had shrunk vehicles and trees to about 1 m. |
| The base game ([kartik786-git/gta-clone-threejs](https://github.com/kartik786-git/gta-clone-threejs)) is fetched at a pinned commit, not vendored; its committed `node_modules/` is skipped and `npm ci` runs instead | It has no license file (used with attribution), and its `node_modules` is broken on macOS: one model once spent budget repairing it. |

## Gotchas

- **Don't read `~/.claude/settings.json`** (credentials; the permission classifier blocks it). Use `nexus claude status`.
- **`claude --bare` breaks Nexus routing,** and `--dangerously-skip-permissions` is blocked. The harness uses `--permission-mode acceptEdits` plus `--allowed-tools`, and the sandbox does the confining.
- **The shell is zsh:** `$VAR` with spaces doesn't word-split, unmatched globs abort the command, and a variable named `path` overwrites `$PATH`. Use `bash -c` for loops.
- **Launch real races detached** (`nohup ... &`). Foreground commands can be killed (exit 137), and Claude Code background tasks are capped.
- **Anything that runs inside the sandbox** (the Stop hook, `tools/screenshot`) must be in `seed.TOOLKIT_MODULES`: the sandbox can't read this repo.
- **The Stop hook doesn't fire on API errors** (Claude Code sends `StopFailure` instead), and Claude Code overrides it after 8 blocks in a row with no tool call.
- **Effort may not reach Kimi:** whether Claude Code sends an effort level for a gateway model isn't documented. Kimi can't turn thinking off anyway.
- **Background subagents in `-p` mode** are killed 10 idle minutes after a session ends.
- **Critics are slow, not expensive.** At max effort a review takes about an hour (minutes of thinking between tool calls) but costs $0.05–0.50, so each round takes roughly twice as long as its builder turn alone.
- **Screenshots** need a network-idle wait, a ~12 s settle (the base game parses models between downloads) and a click with the pointer-lock shim (`snapshot.POINTER_LOCK_SHIM`). Headless Chromium also needs the SwiftShader flags.
- **Catalog determinism:** part names come from the glTF JSON, not trimesh (which adds random suffixes), and Rocketbox/Kenney facts come from upstream `metadata.jsonl` (meshopt files trimesh can't decode). An unchanged rebuild is byte-identical.
- **JSON has no `Infinity`:** USD's unlimited joint limits are written as `null`, and everything is written with `allow_nan=False`.
- **The HF cache lives under `~/.cache`:** any "skip `.cache`" filter must test the path relative to the snapshot folder.
- **To check a `.glb` visually,** load it in a headless three.js page with Playwright (SwiftShader) and screenshot it.

## Status

| | |
|---|---|
| Harness, sandbox, critic loop, review trace (`buildoff reviews`), tests (68), docs | ✅ Built; prompts tagged `prompt-v7` |
| Asset dataset (1,302 assets) | ✅ Published; revision pinned in `HF_ASSETS_REVISION` |
| $25 dry runs with the critic loop (`v7-full-25usd-001`, `v7-prim-25usd-001`) | 🟡 Running. Kimi, primitives: `tier4` at $6.04 after one turn and one review. Opus, full: `budget` at $25.11; its $21.5 first turn left no money to fix the crash bug its critic found (Tier 1). Kimi full and Opus primitives still going |
| Scoring checklist per tier, locked before the race | ⬜ Deferred: first see whether the races produce real games |
| The two $100 races | ⬜ Needs the user's explicit OK (up to $400) |
| Blind judging, write-up, video | ⬜ |
| Part 2 (RL on Fireworks) | ⬜ Separate project |

**Open items:**
- The Opus side bills through the user's Claude login; a strict "$100 at list price" claim needs an Anthropic API key in Nexus.
- Scoring: a per-tier pass/fail checklist locked before the race and counted only on runtime evidence, blind pairwise playtests, at least two outside-family AI judges in both orders, and a transcript review for gaming. The research behind it is in the local, gitignored `reports/` folder.
- Repeat runs (2–3 per side) would show whether a win is real. Not approved.

## Next up

1. Finish the two $25 runs; the user plays the builds and reads the critic trace (`buildoff reviews`).
2. Decide whether $25 is enough for Opus at max effort, then both $100 races in parallel, unattended (needs the user's OK).
3. Write and lock the scoring checklist.
4. Judge, write up as "model + Claude Code + provider", fill `HUMANS.md`'s Results, render the video.

## Spend so far

About **$93** on development, smoke tests and dry runs before `prompt-v7`. The biggest items: $35.54 for the two $25 dry runs on 2026-11-22 (voided by Mac sleep), $20.26 for the first $25 dry run, and $19.58 for the two $100 races stopped early on 2026-11-23 to switch to the critic loop. The two $25 runs on `prompt-v7` can add up to $100; they were at about $60 on the evening of 2026-11-23.
