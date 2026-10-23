"""Use the existing Claude sandbox launcher and require structured output."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, cast


def command(prompt: Path, checkout: Path, model: str = "sonnet") -> tuple[list[str], None, Path]:
    """Build one contained Claude worker command without another launch path."""
    if prompt.is_symlink() or not prompt.is_file() or not checkout.is_dir():
        raise ValueError("Claude prompt or checkout is invalid")
    launcher = Path(__file__).resolve().parents[3] / "scripts/sandbox/spawn_sandboxed_worker.py"
    if not launcher.is_file():
        raise ValueError("Claude sandbox launcher is missing")
    return [sys.executable, str(launcher), "--driver", str(checkout), str(prompt), model], None, prompt


def _failed(code: str) -> dict[str, str]:
    """Code a failed worker without interpreting unstructured prose."""
    return {"outcome": "failed", "evidence": f"claude:{code}"}


def result(output: Path, exit_code: int) -> dict[str, Any]:
    """Read a successful final stream result with a closed structured payload."""
    if exit_code:
        return _failed(f"process_exit_{exit_code}")
    try:
        decoded: list[object] = [
            json.loads(line) for line in output.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
    except (OSError, ValueError):
        return _failed("invalid_raw_output")
    if not decoded or not all(isinstance(row, dict) for row in decoded):
        return _failed("invalid_event_stream")
    rows = [cast(dict[str, Any], row) for row in decoded]
    if rows[0].get("type") != "system" or rows[0].get("subtype") != "init":
        return _failed("missing_session_init")
    if not isinstance(rows[0].get("session_id"), str) or not rows[0]["session_id"]:
        return _failed("missing_session_identity")
    if sum(row.get("type") == "result" for row in rows) != 1:
        return _failed("invalid_terminal_count")
    terminal = rows[-1]
    if (
        terminal.get("type") != "result"
        or terminal.get("subtype") != "success"
        or terminal.get("is_error") is not False
    ):
        return _failed("missing_terminal_success")
    raw: object = terminal.get("structured_output")
    if not isinstance(raw, dict):
        return _failed("missing_structured_output")
    parsed = cast(dict[str, Any], raw)
    if (
        set(parsed) != {"outcome", "evidence"}
        or parsed["outcome"] not in {"done", "failed"}
        or not isinstance(parsed["evidence"], str)
        or not parsed["evidence"].strip()
    ):
        return _failed("invalid_final_schema")
    return parsed


def run_wave(
    path: Path, session: str, checkout: Path, script: Path, runner: Callable[..., dict[str, Any]]
) -> dict[str, Any]:
    """Select Claude's role model and call the shared foreground controller."""
    models = {"fast-mechanical": "haiku", "default": "sonnet", "frontier": "opus"}

    def select(prompt: Path, record: dict[str, Any]) -> tuple[list[str], None, Path]:
        """Pin the model to the frozen dispatch role."""
        return command(prompt, checkout, models[record["contract"]["model_role"]])

    return runner(
        path,
        session,
        script,
        checkout,
        "claude",
        select,
        result,
    )
