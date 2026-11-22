"""Harness for the $100 GTA Build-Off.

Runs two models side by side in headless Claude Code, each building a game from the
same spec, with Nexus as router, referee (spend) and telemetry.

Start reading at `harness.race` (the CLI entry point), then `harness.runner`
(one contender's turn loop). Supporting modules:

- `harness.config`: contenders, limits, paths
- `harness.meter`: reads spend and model identity from `nexus claude usage`
- `harness.sandbox`: per-contender sandbox-exec profile and scrubbed environment
- `harness.snapshot`: per-turn git commit and headless screenshot of the game
- `harness.viewer`: pretty-prints a contender's live transcript in a terminal
"""
