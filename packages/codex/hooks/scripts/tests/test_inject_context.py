#!/usr/bin/env python3
"""Focused behavioral coverage for the Codex UserPromptSubmit context hook."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NoReturn, cast

HOOK = Path(__file__).resolve().parent.parent / "inject_context.py"


def run(payload: str) -> subprocess.CompletedProcess[str]:
    """Run the hook with one synthetic JSON payload."""
    return subprocess.run([sys.executable, str(HOOK)], input=payload, text=True, capture_output=True, check=False)


def fail(message: str) -> NoReturn:
    """Report a focused-test failure and exit non-zero."""
    print(f"test_inject_context: {message}", file=sys.stderr)
    raise SystemExit(1)


def context_for(payload: str) -> str:
    """Run the hook and extract its additional context string."""
    result = run(payload)
    if result.returncode != 0:
        fail(f"hook exited {result.returncode}: {result.stderr}")
    decoded: object = json.loads(result.stdout)
    if not isinstance(decoded, dict):
        fail(f"output is not an object: {result.stdout}")
    output = cast(dict[str, object], decoded)
    envelope_candidate = output.get("hookSpecificOutput")
    if not isinstance(envelope_candidate, dict):
        fail(f"missing context envelope: {result.stdout}")
    envelope = cast(dict[str, object], envelope_candidate)
    context = envelope.get("additionalContext")
    if not isinstance(context, str):
        fail(f"missing context envelope: {result.stdout}")
    return context


def main() -> int:
    """Cover explicit cwd, fallback cwd, non-git branch, and malformed input."""
    with tempfile.TemporaryDirectory(prefix="coderails-codex-context.") as scratch:
        context = context_for(json.dumps({"cwd": scratch}))
        for expected in (f"cwd={scratch}", "branch=none", "[discipline]"):
            if expected not in context:
                fail(f"context lacks {expected!r}: {context}")
    if "[discipline]" not in context_for("{"):
        fail("malformed input did not preserve the discipline context")
    print("test_inject_context: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
