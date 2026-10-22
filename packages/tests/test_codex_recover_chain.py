"""Recover, re-dispatch, record and verify completion end to end through the real evidence validators."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import graph
from graph_completion import complete, verify_completion

from hooks.scripts.tests.lib import assembled_retro
from packages.tests.codex_fixture import append, frozen_evals, node, read_json, spawn, state, transcripts, write_json
from scripts.lib import proof_results as pr

LEASE = 600
STALLED = 1_789_948_802.0 + LEASE
UNITS = ("U3[1]", "U3[2]")


class RecoverChainTests(unittest.TestCase):
    """Only a unique native spawn per attempt lets recovery, re-dispatch and completion all validate."""

    def setUp(self) -> None:
        """Two independent nodes under a frozen suite."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "parent" / "progress.json"
        self.path.parent.mkdir()
        initial = state()
        initial.update(
            created="2026-10-19T00:00:00+00:00",
            authorising_prompt_raw="Complete the recovered fixture loop.",
        )
        initial["graph"]["nodes"]["U3[2]"] = node(2)
        write_json(self.path, initial)
        write_json(self.path.with_name("evals.json"), frozen_evals())
        self.parent = transcripts(self.directory)

    def _spawn(self, terminal: bool) -> list[Path]:
        """Spawn every unit's current attempt."""
        return [spawn(self.parent, read_json(self.path), unit, terminal=terminal) for unit in UNITS]

    def _record_done(self) -> None:
        """Record every unit done."""
        wave = read_json(self.path)["graph"]["active_wave"]["wave_id"]
        results = {unit: {"outcome": "done", "evidence": "ok"} for unit in UNITS}
        graph.record_wave(self.path, json.dumps({"wave_id": wave, "results": results}))

    def _assemble_retro(self) -> None:
        """Run the prepare CLI, then bind its receipt into the final retro assembly."""
        assembled_retro.write(self.path.parent, "parent")
        state_dir = self.path.parent
        environment = {
            **os.environ,
            "HOME": str(self.directory),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.directory),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.directory),
        }
        prepared = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "scripts/lib/orders.py"),
                "--dir",
                str(state_dir.parent),
                "--session",
                "parent",
                "prepare",
                "--loop",
                read_json(self.path)["loop_id"],
            ],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            cwd=self.directory,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        assembled = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "scripts/lib/retro.py"),
                "assemble",
                str(state_dir),
                "--session",
                "parent",
            ],
            capture_output=True,
            text=True,
            check=False,
            env={**environment, "PATH": "/nonexistent"},
            cwd=self.directory,
        )
        self.assertIn(assembled.returncode, (0, 3), assembled.stderr)

    def _verify(self) -> dict[str, Any]:
        """Freeze a level-0 suite at the current revision and verify completion."""
        evals: dict[str, Any] = frozen_evals() | {
            "verification_level": 0,
            "revision": read_json(self.path)["revision"],
            "evals": [],
            "amendments": [],
            "result": "VERIFICATION_LEVEL0",
            "grading": {
                "by": "post_evals.py grade-loop",
                "checksum": hashlib.sha256(b"[]\nVERIFICATION_LEVEL0").hexdigest(),
                "amendments_at_grade": 0,
            },
        }
        suite = self.path.with_name("evals.json")
        write_json(suite, evals)
        proof, retro, log = (self.path.with_name(n) for n in ("proof.json", "retro.json", "proof.jsonl"))
        document = {
            "schema_version": 2,
            "session_id": "parent",
            "loop_id": "loop",
            "proofs": [{"id": "P1", "cmd": "true", "expect": {"exit_code": 0}}],
        }
        write_json(proof, document)
        append(log, {"type": "turn_context", "payload": {"loop_id": "loop"}})
        results = self.path.with_name(pr.RESULTS_NAME)
        identity = {"session_id": "parent", "loop_id": "loop"}
        pr.append(results, kind="freeze", proof_json_sha256=pr.doc_sha(document), **identity)
        pr.append(
            results,
            kind="run",
            proof_id="P1",
            cmd_sha256=pr.sha("true"),
            proof_json_sha256=pr.doc_sha(document),
            verdict="satisfied",
            **identity,
        )
        self._assemble_retro()  # last: the retro binds every source above
        complete(self.path, "parent", suite, proof, retro, log)
        return verify_completion(self.path, "parent", suite, proof, retro, log)

    def test_stalled_then_late_a1_completion_then_a2_done_verifies(self) -> None:
        """A late a1 finish neither breaks a2 validation nor completion."""
        graph.begin_wave(self.path)
        first = self._spawn(terminal=False)
        self.assertTrue(graph.recover_wave(self.path, "parent", LEASE, now=STALLED)["recovered"])
        late = {"timestamp": "2026-09-21T01:00:00Z", "type": "event_msg", "payload": {"type": "task_complete"}}
        for child in first:  # the abandoned a1 workers finish after recovery
            append(child, late)
        wave = graph.begin_wave(self.path)
        self.assertTrue(all(name.endswith("_a2") for name in wave["task_names"].values()))
        self._spawn(terminal=True)
        self._record_done()
        self.assertTrue(self._verify())

    def test_no_spawn_node_is_never_recorded_and_a_late_spawn_verifies(self) -> None:
        """A node that was never spawned changes nothing; spawning it late then records and verifies normally."""
        graph.begin_wave(self.path)
        before = self.path.read_text(encoding="utf-8")
        report = graph.recover_wave(self.path, "parent", LEASE, now=STALLED)
        self.assertEqual((report["recovered"], report["reason_code"]), (False, "no_spawn_dispatch"))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self._spawn(terminal=True)
        self._record_done()
        self.assertTrue(self._verify())


if __name__ == "__main__":
    unittest.main()
