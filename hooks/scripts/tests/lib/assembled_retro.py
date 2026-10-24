"""Fixture helper: a schema 3 retro the completion gates accept, built by the real `retro.py assemble`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

from scripts.lib import retro, teardown_steps


def write(state_dir: Path, session: str, free: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record the teardown steps a fixture loop would have run, assemble beside progress.json, return the retro.

    Call after progress.json, evals.json, proof.json and proof_results.jsonl are final: the retro binds their hashes.
    Muninn is made unreachable while assembling (PATH without it), so a fixture row still pending or degraded stays
    degraded with `muninn_absent` and no test ever reaches a real store. Exit 3 (a degrade) is accepted; 2 is a failure.
    """
    teardown_steps.record(
        state_dir, "proof_run", session, None, teardown_steps.file_sha(state_dir / "proof_results.jsonl")
    )
    with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
        payload, code = retro.assemble(state_dir, session, free)
    if code == 2:
        raise AssertionError(payload)
    loaded: dict[str, Any] = json.loads((state_dir / "retro.json").read_text(encoding="utf-8"))
    return loaded
