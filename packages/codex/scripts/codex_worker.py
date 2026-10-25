#!/usr/bin/env python3
"""Run one Codex worker in a separate, workspace-sandboxed OAuth process."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

MODELS = {"fast-mechanical": "gpt-6-luna", "default": "gpt-6.1-sol", "frontier": "gpt-6-astra"}
PASS_ENV = ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG", "TERM")


def trace(session: str, outcome: str, reason: str) -> bool:
    """Record a countable, body-free launch decision before or after the child."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", session) is None or ".." in session:
        return False
    root = Path(os.environ.get("CODERAILS_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    row: dict[str, object] = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "session_id": session,
        "loop_id": None,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": "codex_worker",
        "outcome": outcome,
        "reason_code": reason,
        "inputs": {},
    }
    try:
        path = root / session / "trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as target:
            target.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def command(
    checkout: Path,
    schema: Path,
    final: Path,
    *,
    model_role: str = "default",
    executable: str | None = None,
) -> list[str]:
    """Build the fixed sandbox command for an isolated feature checkout."""
    if schema.is_symlink() or final.is_symlink():
        raise ValueError("Codex worker artifacts cannot be symlinks")
    checkout = checkout.resolve(strict=True)
    schema = schema.resolve(strict=True)
    final = final.resolve()
    artifact_dir = checkout / ".coderails-worker"
    if not checkout.is_dir() or not schema.is_file():
        raise ValueError("Codex worker checkout or schema is invalid")
    if schema.parent != artifact_dir or final.parent != artifact_dir:
        raise ValueError("Codex worker artifacts must stay in the worker scratch directory")
    if model_role not in MODELS:
        raise ValueError("Codex worker model role is invalid")
    for directory in (checkout, *checkout.parents):
        if (directory / ".codex").exists():
            raise ValueError("project Codex config can add executable controls")
        if (directory / ".git").exists():
            break
    branch = subprocess.run(
        ["git", "-C", str(checkout), "branch", "--show-current"], capture_output=True, text=True, check=False
    )
    if branch.returncode or branch.stdout.strip() in {"", "main", "master"}:
        raise ValueError("Codex worker needs a feature checkout")
    cli = executable or shutil.which("codex")
    if not cli:
        raise ValueError("Codex OAuth CLI is unavailable")
    return [
        cli,
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "-C",
        str(checkout),
        "--json",
        "--model",
        MODELS[model_role],
        "--output-schema",
        str(schema),
        "--output-last-message",
        str(final),
        "-c",
        "features.multi_agent=false",
        "-",
    ]


def environment() -> dict[str, str]:
    """Keep the OAuth location, but exclude unrelated tokens and executable overrides."""
    return {name: os.environ[name] for name in PASS_ENV if name in os.environ}


def run(checkout: Path, prompt: Path, schema: Path, output: Path, final: Path, model_role: str, session: str) -> int:
    """Capture one real child process without treating its prose as a result."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", session) is None or ".." in session:
        raise ValueError("Codex worker session is invalid")
    if prompt.is_symlink() or output.is_symlink():
        raise ValueError("Codex worker prompt or output cannot be symlinks")
    prompt = prompt.resolve(strict=True)
    output = output.resolve()
    root = checkout.resolve(strict=True)
    if not prompt.is_file() or output.parent != root / ".coderails-worker":
        raise ValueError("Codex worker prompt or output is invalid")
    json.loads(schema.read_text(encoding="utf-8"))
    argv = command(root, schema, final, model_role=model_role)
    if not trace(session, "starting", "contained_process_start"):
        raise ValueError("Codex worker containment trace is unavailable")
    with prompt.open("rb") as source, output.open("xb") as target:
        child = subprocess.run(
            argv, stdin=source, stdout=target, stderr=subprocess.STDOUT, env=environment(), check=False
        )
    trace(
        session,
        "allowed" if child.returncode == 0 else "failed",
        "contained_process_complete" if child.returncode == 0 else "contained_process_failed",
    )
    return child.returncode


def main() -> int:
    """Parse one bounded worker launch and record refusal when setup fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("checkout", "prompt", "schema", "output", "final"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument("--model-role", choices=sorted(MODELS), default="default")
    args = parser.parse_args()
    try:
        return run(args.checkout, args.prompt, args.schema, args.output, args.final, args.model_role, args.session)
    except (OSError, ValueError) as error:
        trace(args.session, "refused", "contained_process_unavailable")
        print(f"codex_worker_refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
