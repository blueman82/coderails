"""Create publication-test graph state with the supported controller commands."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def graph_progress(
    repo: Path,
    loop_root: Path,
    manifest: list[str],
    *,
    unit: str = "2",
    session: str = "s",
    provider: str = "claude",
) -> Path:
    """Start a real graph, add one unit, and return its supported state path."""
    environment = os.environ | {
        "CLAUDE_AGENTIC_LOOP_DIR": str(loop_root),
        "CODERAILS_AGENTIC_LOOP_DIR": str(loop_root),
        "CLAUDE_CODE_SESSION_ID": session,
    }
    helper = ROOT / "hooks/scripts/lib/agentic_loop_path.py"
    progress = Path(
        subprocess.check_output([sys.executable, str(helper)], cwd=repo, env=environment, text=True).strip()
    )
    prompt = loop_root / f"{session}-prompt.txt"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("Build the unit")
    graph = (
        ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py"
        if provider == "codex"
        else ROOT / "skills/agentic-loop/scripts/graph.py"
    )
    for command, flags in (
        ("start", ["--prompt-file", str(prompt)]),
        ("add-unit", ["--unit", unit, *[item for glob in manifest for item in ("--manifest", glob)]]),
    ):
        subprocess.run(
            [
                sys.executable,
                str(graph),
                command,
                str(progress),
                "--session",
                session,
                "--loop-id",
                f"manifest-{session}",
                *flags,
            ],
            cwd=repo,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
    return progress
