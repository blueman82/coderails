"""Worktree HEAD change control for the Codex completion fixture."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from graph_completion import complete, verify_completion
from graph_identity import GraphError

from packages.tests.codex_fixture import read_json, write_json


def assert_changed_head(case: Any, assemble: Callable[[Path, str], dict[str, Any]]) -> None:  # noqa: ANN401
    """A proof result from the previous HEAD cannot satisfy current completion."""
    subprocess.run(["git", "-C", str(case.directory), "init", "-q"], check=True)

    def commit(message: str) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(case.directory),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-qm",
                message,
            ],
            check=True,
        )

    commit("first")
    before = Path.cwd()
    try:
        os.chdir(case.directory)
        case.proof_result("satisfied")
        assemble(case.path.parent, "parent")
        complete(*case.arguments)
        commit("second")
        with case.assertRaisesRegex(GraphError, r"P1\(proof_stale_head\)"):
            verify_completion(*case.arguments)
    finally:
        os.chdir(before)


def assert_empty_proof_disposition(case: Any, assemble: Callable[[Path, str], dict[str, Any]]) -> None:  # noqa: ANN401
    """An empty frozen proof file requires an explicit typed disposition."""
    case.document["proofs"] = []
    write_json(case.proof, case.document)
    current = read_json(case.path)
    write_json(
        case.path,
        current | {"proof_disposition": {"kind": "none", "reason_code": "docs_only", "reason": "no executable proof"}},
    )
    assemble(case.path.parent, "parent")
    complete(*case.arguments)
