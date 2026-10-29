"""A sourced disposition between native waves preserves recorded attempts."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))

import graph
from graph_controller import set_unit_disposition
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError

from packages.tests.codex_fixture import read_json, spawn, write_json
from packages.tests.test_codex_graph_runtime import RuntimeFixture


class DispositionRevisionTests(RuntimeFixture):
    """Exercise actual wave recording with native transcript fixtures."""

    def test_choice_between_failed_wave_and_retry_preserves_native_history(self) -> None:
        """A sourced unit choice spends one revision without invalidating an attempt."""
        initial = read_json(self.path)
        initial["work_units"] = {"1": {"status": "pending"}}
        write_json(self.path, initial)
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        self.record("failed")
        before = read_json(self.path)
        changed = set_unit_disposition(
            self.path, "parent", "loop", before["revision"], "1", "clean-break", None, None, "PR #504"
        )
        self.assertEqual(changed["revision"], before["revision"] + 1)
        graph.begin_wave(self.path)
        spawn(self.parent, read_json(self.path))
        self.record()
        final = read_json(self.path)
        validate_worker_evidence(final)
        prior = before["graph"]["nodes"]["U3[1]"]["evidence"]
        self.assertEqual(final["graph"]["nodes"]["U3[1]"]["evidence"][: len(prior)], prior)
        self.assertEqual(final["graph"]["nodes"]["U3[1]"]["status"], "done")
        for field, value in (
            ("disposition_revision", None),
            ("disposition_revision", True),
            ("disposition_revision", final["revision"] + 1),
            ("disposition_revision", 2),
            ("disposition_source", ""),
            ("disposition", {"kind": "unknown"}),
        ):
            with self.subTest(field=field, value=value):
                altered = copy.deepcopy(final)
                altered["work_units"]["1"][field] = value
                with self.assertRaisesRegex(GraphError, "graph revisions"):
                    validate_worker_evidence(altered)


if __name__ == "__main__":
    unittest.main()
