#!/usr/bin/env python3
"""Versioned progress.json conversion: v0 converts once, ambiguity is refused unchanged, on both providers."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/agentic-loop/scripts"))
import graph as claude_graph
import graph_contract
import graph_convert

from hooks.scripts.tests.lib import claude_transcript_fixture as claude

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = {
    "claude": ROOT / "skills/agentic-loop/scripts/graph.py",
    "codex": ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py",
}
SESSION = "S"


def v0_state() -> dict[str, Any]:
    """A schema-3 state exactly as the old `start` plus one unit wrote it: no state_minor, stops or wave_history."""
    state = claude.state(1)
    state.update(session_id=SESSION, loop_id="L")
    state.pop("state_minor")
    for key in ("dispatches", "contract_from_revision"):
        state["graph"].pop(key)
    return state


def v1_state(revision: int = 3, active: bool = False) -> dict[str, Any]:
    """A state as minor 1 wrote it: history present, no dispatch records yet."""
    state = v0_state()
    state.update(state_minor=1, stops=[], revision=revision)
    state["graph"]["wave_history"] = {}
    if active:
        state["graph"]["active_wave"] = {"wave_id": "wave-3", "nodes": ["U3[1]"], "revision": 3}
        state["graph"]["wave_history"]["wave-3"] = {"cursor": 0, "nodes": ["U3[1]"], "revision": 3}
        state["graph"]["nodes"]["U3[1]"].update(status="running", outcome="running")
    return state


class Case:
    """One provider's state file and its real `graph.py convert` entrypoint."""

    def __init__(self, name: str, home: Path) -> None:
        """Create the state directory for this provider."""
        self.name = name
        self.path = home / name / SESSION / "progress.json"
        self.path.parent.mkdir(parents=True)
        self.write(v0_state())

    def write(self, state: object) -> None:
        """Replace the state file."""
        self.path.write_text(json.dumps(state, indent=2))

    def read(self) -> dict[str, Any]:
        """Read the state file."""
        return dict(json.loads(self.path.read_text()))

    def graph(self, command: str, *flags: str, session: str = SESSION) -> subprocess.CompletedProcess[str]:
        """Run one graph.py command that takes --session."""
        return subprocess.run(
            [sys.executable, str(SCRIPTS[self.name]), command, str(self.path), "--session", session, *flags],
            capture_output=True,
            text=True,
            check=False,
        )

    def inspect(self) -> subprocess.CompletedProcess[str]:
        """Run the real validating reader."""
        return subprocess.run(
            [sys.executable, str(SCRIPTS[self.name]), "inspect", str(self.path)],
            capture_output=True,
            text=True,
            check=False,
        )

    @property
    def backup(self) -> Path:
        """The one-time pre-conversion copy."""
        return self.path.with_name("progress.json.pre-convert")

    def reasons(self) -> list[str]:
        """Convert reason codes traced beside the state, oldest first."""
        trace = self.path.with_name("recovery-trace.jsonl")
        rows = [json.loads(line) for line in trace.read_text().splitlines()] if trace.is_file() else []
        return [row["reason_code"] for row in rows if row.get("command") == "convert"]


class GraphConvertTests(unittest.TestCase):
    """Drive the real `graph.py convert` of each provider against the same v0 state."""

    def setUp(self) -> None:
        """Create one isolated Claude and one isolated Codex state."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.cases = [Case(name, Path(temporary.name)) for name in ("claude", "codex")]

    def test_v0_converts_validates_and_a_second_run_is_a_no_op(self) -> None:
        """A v0 state gains the typed containers, keeps a backup of the original, and converts only once."""
        for case in self.cases:
            original = case.path.read_bytes()
            result = case.graph("convert")
            self.assertEqual(result.returncode, 0, (case.name, result.stderr))
            report = json.loads(result.stdout)
            self.assertEqual((report["changed"], report["from"], report["to"]), (True, 0, 3))
            state = case.read()
            self.assertEqual((state["state_minor"], state["stops"], state["graph"]["wave_history"]), (3, [], {}))
            self.assertEqual((state["graph"]["dispatches"], state["graph"]["contract_from_revision"]), ({}, 1))
            self.assertEqual(state["graph"]["context_from_revision"], 1)
            self.assertIn("updated_at", state)
            self.assertEqual(case.backup.read_bytes(), original)
            self.assertEqual(case.inspect().returncode, 0, case.name)  # the real reader still accepts it
            after = case.path.read_bytes()
            again = case.graph("convert")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertFalse(json.loads(again.stdout)["changed"])
            self.assertEqual(case.path.read_bytes(), after)
            self.assertEqual(case.backup.read_bytes(), original)
            self.assertEqual(case.reasons(), ["convert_ok", "convert_ok"])

    def test_v1_gains_dispatch_records_from_its_current_revision(self) -> None:
        """v1 -> v2 adds an empty dispatches object and stamps contract_from_revision; an active wave is refused."""
        for case in self.cases:
            case.write(v1_state(revision=3))
            result = case.graph("convert")
            self.assertEqual(result.returncode, 0, (case.name, result.stderr))
            self.assertEqual(json.loads(result.stdout)["steps"], ["v1->v2", "v2->v3"])
            state = case.read()
            self.assertEqual((state["state_minor"], state["graph"]["dispatches"]), (3, {}))
            self.assertEqual(state["graph"]["contract_from_revision"], 3)
            self.assertEqual(state["graph"]["context_from_revision"], 3)
            case.backup.unlink()
            case.write(v1_state(active=True))
            before = case.path.read_bytes()
            refused = case.graph("convert")
            self.assertNotEqual(refused.returncode, 0, case.name)
            self.assertIn("active_wave_in_flight", refused.stderr)
            self.assertEqual(case.path.read_bytes(), before)
            self.assertFalse(case.backup.exists())
            self.assertEqual(case.reasons()[-1], "convert_refused_active_wave_in_flight")

    def test_v2_context_conversion_refuses_torn_or_open_dispatch_state(self) -> None:
        """Only an idle, valid v2 state gets a context cutoff; refusals preserve its bytes."""
        for case in self.cases:
            old = v1_state(revision=3)
            old["state_minor"] = 2
            old["graph"].update(dispatches={}, contract_from_revision=2)
            case.write(old)
            result = case.graph("convert")
            self.assertEqual(result.returncode, 0, (case.name, result.stderr))
            state = case.read()
            self.assertEqual(state["state_minor"], 3)
            self.assertEqual(state["graph"]["context_from_revision"], 3)
            case.backup.unlink()
            broken_cases: list[dict[str, Any]] = [
                {**old, "graph": {**old["graph"], "dispatches": []}},
                {**old, "graph": {**old["graph"], "dispatches": {"disp_torn": {}}}},
                {**old, "graph": {**old["graph"], "contract_from_revision": "2"}},
                {**old, "graph": {**old["graph"], "active_wave": {"wave_id": "wave-3", "nodes": []}}},
            ]
            contract = graph_contract.build_contract(old, "U3[1]", "main")
            del contract["required_context"]
            broken_cases.append(
                {
                    **old,
                    "graph": {
                        **old["graph"],
                        "dispatches": {
                            "disp_equal_revision": {
                                "node_id": "U3[1]",
                                "wave_id": "wave-3",
                                "revision": old["revision"],
                                "attempt": 1,
                                "envelope_version": graph_contract.ENVELOPE_VERSION,
                                "contract": contract,
                                "prompt_sections_sha256": graph_contract.sections_sha256(contract),
                            }
                        },
                    },
                }
            )
            for broken in broken_cases:
                case.write(broken)
                before = case.path.read_bytes()
                refused = case.graph("convert")
                self.assertNotEqual(refused.returncode, 0, (case.name, refused.stderr))
                self.assertEqual(case.path.read_bytes(), before)
                self.assertFalse(case.backup.exists())

    def test_check_never_writes(self) -> None:
        """--check reports the pending conversion and leaves the file and the backup alone."""
        for case in self.cases:
            before = case.path.read_bytes()
            result = case.graph("convert", "--check")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["changed"])
            self.assertEqual(case.path.read_bytes(), before)
            self.assertFalse(case.backup.exists())

    def test_current_minor_missing_contract_stamp_is_not_a_no_op(self) -> None:
        """A current minor with no contract cutoff cannot silently bypass revalidation."""
        for case in self.cases:
            current, _ = graph_convert.convert(v1_state(), SESSION)
            del current["graph"]["contract_from_revision"]
            case.write(current)
            before = case.path.read_bytes()
            result = case.graph("convert")
            self.assertNotEqual(result.returncode, 0, case.name)
            self.assertIn("dispatch_state_unconverted", result.stderr)
            self.assertEqual(case.path.read_bytes(), before)

    def test_every_ambiguity_is_refused_with_bytes_unchanged(self) -> None:
        """Unknown schema, future or bad minor, in-flight wave, torn stops or units and a foreign session all refuse."""
        for case in self.cases:
            base = case.read()
            in_flight = copy.deepcopy(base)  # a wave is open but no wave_history entry records its cursor
            in_flight["graph"]["active_wave"] = {"wave_id": "wave-1", "nodes": ["U3[1]"], "revision": 1}
            cases: dict[str, dict[str, Any]] = {
                "unknown_schema": {**base, "schema_version": 2},
                "minor_future": {**base, "state_minor": 9},
                "minor_invalid": {**base, "state_minor": "1"},
                "malformed_stops": {**base, "stops": "torn"},
                "malformed_work_units": {**base, "work_units": []},
                "graph_not_object": {**base, "graph": []},
                "active_wave_ambiguous": in_flight,
            }
            current_in_flight = copy.deepcopy(in_flight)
            current_in_flight["state_minor"] = 1
            current_in_flight["graph"]["wave_history"] = {}
            for code, state in cases.items():
                case.write(state)
                before = case.path.read_bytes()
                result = case.graph("convert")
                self.assertNotEqual(result.returncode, 0, (case.name, code))
                self.assertIn(code, result.stderr)
                self.assertEqual(case.path.read_bytes(), before, (case.name, code))
                self.assertFalse(case.backup.exists(), (case.name, code))
                self.assertEqual(case.reasons()[-1], f"convert_refused_{code}")
            case.write(current_in_flight)
            before = case.path.read_bytes()
            result = case.graph("convert")
            self.assertNotEqual(result.returncode, 0, case.name)
            self.assertIn("active_wave_ambiguous", result.stderr)
            self.assertEqual(case.path.read_bytes(), before)
            self.assertFalse(case.backup.exists())
            unhashable = copy.deepcopy(in_flight)
            unhashable["graph"]["active_wave"]["wave_id"] = []
            case.write(unhashable)
            before = case.path.read_bytes()
            result = case.graph("convert", "--check")
            self.assertNotEqual(result.returncode, 0, case.name)
            self.assertIn("active_wave_ambiguous", result.stderr)
            self.assertEqual(case.path.read_bytes(), before)
            self.assertEqual(case.reasons()[-1], "convert_refused_active_wave_ambiguous")
            case.write(base)
            before = case.path.read_bytes()
            self.assertIn("foreign_session", case.graph("convert", session="someone-else").stderr)
            self.assertEqual(case.path.read_bytes(), before)

    def test_claude_failed_atomic_write_never_reports_success(self) -> None:
        """A failed locked write must keep source bytes and avoid convert_ok even after a report was built."""
        case = self.cases[0]
        before = case.path.read_bytes()

        def fail_after_transform(path: Path, update: Callable[[dict[str, Any]], dict[str, Any]]) -> bool:
            update(json.loads(path.read_text()))
            return False

        with (
            patch.object(claude_graph, "atomic_progress_update", side_effect=fail_after_transform),
            self.assertRaisesRegex(ValueError, "locked|unreadable|write"),
        ):
            claude_graph.convert_state(case.path, SESSION, False)
        self.assertEqual(case.path.read_bytes(), before)
        self.assertEqual(case.backup.read_bytes(), before)
        self.assertNotIn("convert_ok", case.reasons())

    def test_existing_backup_is_never_overwritten(self) -> None:
        """A stale .pre-convert refuses the conversion rather than being replaced or deleted."""
        for case in self.cases:
            case.backup.write_text("older backup")
            before = case.path.read_bytes()
            result = case.graph("convert")
            self.assertIn("backup_exists", result.stderr)
            self.assertEqual(case.path.read_bytes(), before)
            self.assertEqual(case.backup.read_text(), "older backup")

    def test_both_providers_produce_the_same_converted_state(self) -> None:
        """Same input, same report and same converted bytes apart from the write stamp."""
        outputs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for case in self.cases:
            report = json.loads(case.graph("convert").stdout)
            state = case.read()
            state.pop("updated_at")
            outputs.append((report, state))
        self.assertEqual(outputs[0], outputs[1])

    def test_convert_is_pure(self) -> None:
        """The pure function never mutates its input and a current state comes back identical."""
        source = v0_state()
        snapshot = copy.deepcopy(source)
        converted, _ = graph_convert.convert(source)
        self.assertEqual(source, snapshot)
        again, report = graph_convert.convert(converted)
        self.assertEqual((again, report["changed"]), (converted, False))


if __name__ == "__main__":
    unittest.main()
