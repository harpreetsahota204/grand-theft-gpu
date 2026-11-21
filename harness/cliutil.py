"""Shared CLI plumbing for agent-facing commands.

Every command an agent might call (`buildoff`, `tools/screenshot`) reports
usage errors the same way: one JSON object on stderr and exit code 2, instead
of argparse's free-text usage dump. Agents can parse it and self-correct.
"""

import argparse
import json
import sys
from typing import NoReturn


class JsonErrorParser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors are {"error", "hint"} JSON on stderr (exit 2)."""

    def error(self, message: str) -> NoReturn:
        """Reports a usage error as JSON instead of free text, then exits 2."""
        hint = f"run: {self.prog} --help"
        sys.stderr.write(json.dumps({"error": message, "hint": hint}) + "\n")
        sys.exit(2)
