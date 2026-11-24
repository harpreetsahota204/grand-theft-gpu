"""Per-contender Claude Code configuration: `--settings` files (builder, critic) and `--agents`.

`harness.runner` calls `write` once per contender after seeding. Every builder
turn gets `--settings SETTINGS_FILE --agents AGENTS_FILE`; every critic review
gets `--settings CRITIC_SETTINGS_FILE`. They live in the
contender's toolkit folder, which its sandbox can read but not write. The two
contenders' files are identical except for the model ID, so the same rules hold
on both sides:

- **Model pinning.** Every tier alias (opus/sonnet/haiku/fable, which Claude
  Code also uses for background work) and every subagent resolves to the
  contender's own model; `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` stops a spawn call
  or an agent definition from naming another one. The leak check in
  `harness.runner` still watches Nexus in case anything slips through.
- **Same effort and compaction.** Both sides run at the same reasoning effort
  and compact at the same context size, instead of each model's own default.
- **The Stop hook** (`harness.stop_hook`, builder only), whose reason is the
  last line of the locked nudge template ("Keep building the game toward Tier 4.").
- **One playtester subagent**, read-only, that plays the game with
  `tools/screenshot` and reports what's broken or missing. It's optional for
  the model to use; it never edits files.

`--settings` overrides the same keys in ~/.claude/settings.json (where Nexus
keeps its routing), and only for the keys set here.
"""

import json
import shlex
import sys
from pathlib import Path

from harness.config import AUTO_COMPACT_WINDOW, EFFORT_LEVEL, PROMPTS_DIR

SETTINGS_FILE: str = "claude-settings.json"
# The critic's settings: the same pins, effort and compaction, but no Stop hook
# (the hook would push the critic to keep working on a broken build).
CRITIC_SETTINGS_FILE: str = "critic-settings.json"
AGENTS_FILE: str = "claude-agents.json"
# The Stop hook reads its fixed reason from here (see hook_reason).
REASON_FILE: str = "hook-reason.txt"
# Long enough for the hook's `npm run build` check (stop_hook.BUILD_TIMEOUT_S).
STOP_HOOK_TIMEOUT_S: int = 180
TIER_ALIASES: tuple[str, ...] = ("OPUS", "SONNET", "HAIKU", "FABLE")

PLAYTESTER_PROMPT: str = """\
You are a QA playtester for the browser game in the current folder. You do not \
change the game.

Build and play it with `tools/screenshot` (run `tools/screenshot --help`; \
`--hold KEY:MS` holds a key, e.g. `--hold w:2000` to move forward, and \
`--out PATH` saves extra shots). Open each PNG with the Read tool and look at it \
closely. Read the source only to understand what you see.

Report back, most important first:
1. What is broken: errors, a blank or black screen, controls that do nothing, \
things that fall through the world.
2. What is missing compared with what you were asked to check.
3. What works.

Be concrete: name the key you pressed, what you expected, and what happened. \
Never edit, create or delete project files."""


def env(model: str) -> dict[str, str]:
    """The environment overrides for one contender: model pins, effort, compaction."""
    pins = {f"ANTHROPIC_DEFAULT_{tier}_MODEL": model for tier in TIER_ALIASES}
    return pins | {
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1",
        "CLAUDE_CODE_EFFORT_LEVEL": EFFORT_LEVEL,
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW": AUTO_COMPACT_WINDOW,
    }


def settings(model: str, toolkit: Path) -> dict[str, object]:
    """The `--settings` content for one contender.

    Args:
        model: the contender's model ID, as passed to `--model`
        toolkit: the contender's toolkit folder (holds the hook module and nudge)

    Returns:
        a JSON-ready settings dict
    """
    toolkit = toolkit.resolve()
    hook = (
        f"PYTHONPATH={shlex.quote(str(toolkit))} {shlex.quote(sys.executable)} "
        f"-m harness.stop_hook {shlex.quote(str(toolkit / REASON_FILE))}"
    )
    return {
        "env": env(model),
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": hook, "timeout": STOP_HOOK_TIMEOUT_S}]}
            ]
        },
    }


def hook_reason() -> str:
    """The Stop hook's fixed reason: the closing line of the locked nudge template.

    The full template wraps the critic's notes, which don't exist mid-turn, so
    the hook uses only its fixed instruction.
    """
    lines = [ln.strip() for ln in (PROMPTS_DIR / "nudge.md").read_text().splitlines()]
    return next(ln for ln in reversed(lines) if ln and "{notes}" not in ln)


def agents() -> dict[str, object]:
    """The `--agents` content: the read-only playtester, identical for every contender."""
    return {
        "playtester": {
            "description": (
                "Read-only QA playtester. Builds and plays the current game with "
                "tools/screenshot and reports what is broken, what is missing and "
                "what works. Use it to check the game with fresh eyes. It never "
                "edits files."
            ),
            "prompt": PLAYTESTER_PROMPT,
            "tools": ["Bash", "Read"],
            "disallowedTools": ["Edit", "Write"],
            "model": "inherit",
        }
    }


def write(toolkit: Path, model: str) -> None:
    """Writes the builder and critic settings, the agents file and the hook reason into a toolkit.

    The runner passes `toolkit/SETTINGS_FILE` and `toolkit/AGENTS_FILE` to
    every turn (`--settings`, `--agents`).

    Args:
        toolkit: the contender's toolkit folder (already created by seeding)
        model: the contender's model ID
    """
    (toolkit / REASON_FILE).write_text(hook_reason() + "\n")
    (toolkit / SETTINGS_FILE).write_text(json.dumps(settings(model, toolkit), indent=2) + "\n")
    (toolkit / CRITIC_SETTINGS_FILE).write_text(json.dumps({"env": env(model)}, indent=2) + "\n")
    (toolkit / AGENTS_FILE).write_text(json.dumps(agents(), indent=2) + "\n")
