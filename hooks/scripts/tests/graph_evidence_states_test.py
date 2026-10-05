"""All-node-state regression for Claude completion-time evidence revalidation (mirrors Codex native evidence)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_evidence_revalidate import revalidate_all
from hooks.scripts.tests.claude_graph_test_support import GraphCase, load, write_records


class EvidenceStateTests(GraphCase):
    """Non-terminal nodes need no evidence; done, skipped, retried and stale ones fail closed."""

    def _sibling(self, state: dict[str, Any], status: str, attempts: int = 0) -> dict[str, Any]:
        variant = copy.deepcopy(state)
        variant["graph"]["nodes"]["U3[2]"] = {
            **copy.deepcopy(variant["graph"]["nodes"]["U3[1]"]),
            "status": status,
            "outcome": status,
            "retry": {"attempts": attempts},
            "evidence": [],
        }
        return variant

    def test_non_terminal_siblings_need_no_completion_evidence(self) -> None:
        """Pending, ready and running nodes need no evidence."""
        state = self.finish()
        for status in ("pending", "ready", "running"):
            with self.subTest(status=status):
                revalidate_all(self._sibling(state, status))

    def test_terminal_and_retried_siblings_fail_closed(self) -> None:
        """Done, skipped, stale and retried nodes without evidence are rejected."""
        state = self.finish()
        for status, attempts in (("done", 0), ("skipped", 0), ("stale", 0), ("pending", 1)):
            with self.subTest(status=status, attempts=attempts), self.assertRaisesRegex(ValueError, "attempt history"):
                revalidate_all(self._sibling(state, status, attempts))

    def test_retry_exhausted_without_attempt_evidence_fails_closed(self) -> None:
        """Retry-exhausted nodes must keep every attempt's evidence."""
        variant = self.finish()
        node = variant["graph"]["nodes"]["U3[1]"]
        node.update(status="failed", outcome="failed", evidence=[])
        node["retry"]["attempts"] = 3
        with self.assertRaisesRegex(ValueError, "attempt history"):
            revalidate_all(variant)

    def test_stale_transcript_reference_fails_closed(self) -> None:
        """A bound reference whose transcript vanished is rejected."""
        state = self.finish()
        revalidate_all(state)
        write_records(self.parent, [])
        with self.assertRaises(ValueError):
            revalidate_all(state)

    def test_never_dispatched_graph_without_wave_history(self) -> None:
        """A graph with only non-terminal nodes and no wave_history must not raise."""
        state = load(self.path)
        state["graph"].pop("wave_history", None)
        revalidate_all(state)


if __name__ == "__main__":
    unittest.main()
