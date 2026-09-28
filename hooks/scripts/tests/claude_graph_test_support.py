"""Shared current-contract graph fixtures for migrated Claude safety suites."""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_dispatch as dispatch
from hooks.scripts.lib.graph_executor import load
from hooks.scripts.tests.lib import claude_transcript_fixture as fixture

__all__ = ["ROOT", "GraphCase", "dispatch", "fixture", "load", "node", "read_records", "write_records"]

ROOT = Path(__file__).resolve().parents[3]


def node(identifier: str, status: str = "pending") -> dict[str, Any]:
    """Construct a registry-labelled node without using private production helpers."""
    labels = {
        "S2": "Run preflight",
        "S2.5": "Resolve design fork",
        "S2.6": "Choose disposition",
        "J2": "Preflight decisions joined",
        "S2.7a": "Write specification",
        "S2.7c": "Freeze loop evals",
        "S2.7e": "Freeze proof plan",
        "S2.8": "Assign model roles",
        "J2.8": "Implementation ready",
        "J12-all-units": "All units joined",
        "S9-wiki": "Update wiki",
        "S9-docs": "Sync docs",
        "U3[1]": "Build unit 1",
        "U3[2]": "Build unit 2",
        "U3[3]": "Build unit 3",
        "S2.7d[1]": "Freeze unit 1 evaluation",
        "S2.7d[10]": "Freeze unit 10 evaluation",
        "U4[1]": "Verify unit artifact 1",
        "U4b-merge-gate[1]": "Merge gate unit 1",
        "U4b-merge-gate[2]": "Merge gate unit 2",
    }
    result: dict[str, Any] = copy.deepcopy(fixture.state()["graph"]["nodes"]["U3[1]"])
    result.update(label=labels[identifier], status=status, outcome=status)
    return result


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read fixture JSONL for single-field negative-control transformations."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_records(path: Path, values: list[dict[str, Any]]) -> None:
    """Rewrite fixture records deliberately, preserving non-targeted records."""
    path.write_text("".join(json.dumps(value) + "\n" for value in values))


class GraphCase(unittest.TestCase):
    """Give every safety case independent native ownership and durable state."""

    def setUp(self) -> None:
        """Allocate provider-owned transcript paths and fast isolated lock settings."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        environment = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "CLAUDE_PROJECTS_DIR": str(self.home / ".claude/projects"),
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.home / "state"),
                "CLAUDE_DISCIPLINE_LOG": str(self.home / "discipline.log"),
                "CLAUDE_HOOK_MAX_ATTEMPTS": "100",
                "CLAUDE_HOOK_SLEEP_S": "0.01",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.path = self.home / "loop/progress.json"
        self.parent = fixture.parent(self.home)
        self.save(fixture.state())

    def save(self, state: dict[str, Any]) -> None:
        """Persist fixture input outside production transitions."""
        fixture.write_json(self.path, state)

    def opened(self) -> dict[str, Any]:
        """Open a real wave, verifying the adapter's saved state."""
        dispatch.begin_wave(self.path)
        return load(self.path)

    def finish(self, outcome: str = "done") -> dict[str, Any]:
        """Drive actual native fixture launches and a whole-wave record."""
        state = self.opened()
        for identifier in state["graph"]["active_wave"]["nodes"]:
            fixture.spawn(self.parent, state, identifier, completed=outcome == "done")
        dispatch.record_wave(self.path, fixture.report(state, outcome))
        return load(self.path)

    def refuse_report(self, report: dict[str, Any], reason: str = ".") -> None:
        """Assert the named refusing mechanism and byte-for-byte atomicity."""
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, reason):
            dispatch.record_wave(self.path, report)
        self.assertEqual(self.path.read_bytes(), original)

    def refuse_completion(self, reason: str = ".") -> None:
        """Check native completion revalidation without artifact gates masking it."""
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, reason):
            dispatch.validate_graph_completion(self.path, "fixture-session")
        self.assertEqual(self.path.read_bytes(), original)
