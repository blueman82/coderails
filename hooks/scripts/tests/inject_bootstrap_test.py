#!/usr/bin/env python3
"""Focused contract checks for the SessionStart bootstrap hook."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import cast

SCRIPT_DIR = Path(__file__).resolve().parent.parent
HOOK = SCRIPT_DIR / "inject_bootstrap.py"
PLUGIN_ROOT = SCRIPT_DIR.parent.parent


def run(payload: dict[str, object], plugin_root: Path = PLUGIN_ROOT) -> dict[str, object]:
    """Run the hook and return its JSON output."""
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin_root)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    decoded: object = json.loads(result.stdout)
    assert isinstance(decoded, dict)
    return cast(dict[str, object], decoded)


def context(output: dict[str, object]) -> str:
    """Return the hook additional context from a valid output envelope."""
    value = output["hookSpecificOutput"]
    assert isinstance(value, dict)
    hook_output = cast(dict[str, object], value)
    assert hook_output["hookEventName"] == "SessionStart"
    result = hook_output["additionalContext"]
    assert isinstance(result, str)
    return result


def main() -> int:
    """Run the focused bootstrap-hook contract checks."""
    assert "using-coderails" in context(run({}))
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        legacy = repo / ".claude"
        legacy.mkdir()
        (legacy / "workflow.config.yaml").write_text("sandbox_workers: true\n", encoding="utf-8")
        assert "/coderails:init" in context(run({"source": "startup", "cwd": str(repo)}))
        assert "/coderails:init" not in context(run({"source": "resume", "cwd": str(repo)}))
        (repo / ".coderails").mkdir()
        (repo / ".coderails" / "workflow.config.yaml").write_text("x: y\n", encoding="utf-8")
        assert "/coderails:init" not in context(run({"source": "startup", "cwd": str(repo)}))
    print("inject_bootstrap_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
