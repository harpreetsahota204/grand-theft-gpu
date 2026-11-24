"""Shared CLI plumbing for agent-facing commands.

Every command an agent might call (`buildoff`, `tools/screenshot`) reports
errors the same way: one {"error", "hint"} JSON object on stderr, exit code 2
for bad input and 1 for anything else, instead of free text. Agents can parse
it and self-correct. Results go to stdout as pretty JSON (`emit`).
"""

import argparse
import json
import sys
from typing import Any, NoReturn


class CliError(Exception):
    """A user-facing failure with a hint on how to fix it.

    Attributes:
        hint: what to try instead, printed with the error
        code: process exit code (1 not found, 2 bad input)
    """

    def __init__(self, message: str, hint: str, code: int = 1) -> None:
        """Stores the message, hint and exit code."""
        super().__init__(message)
        self.hint = hint
        self.code = code


def emit(data: Any) -> None:
    """Writes a result to stdout as stable, pretty-printed JSON."""
    sys.stdout.write(json.dumps(data, indent=2, sort_keys=True) + "\n")


def fail(err: CliError) -> int:
    """Writes an error as JSON to stderr and returns its exit code."""
    sys.stderr.write(json.dumps({"error": str(err), "hint": err.hint}) + "\n")
    return err.code


class JsonErrorParser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors are {"error", "hint"} JSON on stderr (exit 2)."""

    def error(self, message: str) -> NoReturn:
        """Reports a usage error as JSON instead of free text, then exits 2."""
        hint = f"run: {self.prog} --help"
        sys.stderr.write(json.dumps({"error": message, "hint": hint}) + "\n")
        sys.exit(2)
