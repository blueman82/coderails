"""graph_readiness.py prints typed JSON; a missing script is a resolution failure, distinct from not-ready."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.claude_graph_test_support import ROOT, GraphCase, dispatch, fixture, load, node

SCRIPT = ROOT / "hooks/scripts/lib/graph_readiness.py"


class ReadinessTests(GraphCase):
    """Three situations give three distinct reason codes; none is a bare 'blocked'."""

    def query(self, *arguments: str, script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
        """Run the readiness script in a subprocess with trace rows confined to the test home."""
        return subprocess.run(
            [sys.executable, str(script), *arguments],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": str(self.home / "loops")},
        )

    def two_node_state(self) -> dict[str, Any]:
        """Build U3 -> U4 with both pending."""
        state = fixture.state(0)
        state["graph"]["nodes"] = {name: node(name) for name in ("U3[1]", "U4[1]")}
        state["graph"]["edges"] = [{"from": "U3[1]", "to": "U4[1]"}]
        return state

    def test_three_situations_three_codes(self) -> None:
        """ready, predecessor_pending and node_unknown are distinct typed verdicts with matching exit codes."""
        self.save(self.two_node_state())
        before = self.path.read_bytes()
        seen: dict[str, tuple[bool, int]] = {}
        for node_id in ("U3[1]", "U4[1]", "NOPE"):
            result = self.query(str(self.path), node_id)
            verdict = json.loads(result.stdout)
            seen[verdict["reason_code"]] = (verdict["ready"], result.returncode)
        self.assertEqual(seen, {"ready": (True, 0), "predecessor_pending": (False, 1), "node_unknown": (False, 1)})
        self.assertEqual(before, self.path.read_bytes())

    def test_unreadable_state_is_its_own_code(self) -> None:
        """A missing or corrupt progress.json is state_unreadable, not predecessor_pending."""
        self.save(self.two_node_state())
        self.path.write_text("{torn")
        for target in (str(self.path), str(self.path.with_name("missing.json"))):
            result = self.query(target, "U3[1]")
            self.assertEqual(json.loads(result.stdout), {"ready": False, "reason_code": "state_unreadable"})
            self.assertEqual(result.returncode, 1)

    def test_not_ready_leaves_a_trace_row(self) -> None:
        """A readable not-ready verdict is counted: trace graph_readiness/not_ready/<code>."""
        self.save(self.two_node_state())
        self.query(str(self.path), "U4[1]")
        rows = list((self.home / "loops").glob("*/trace.jsonl"))
        self.assertEqual(len(rows), 1)
        row = json.loads(rows[0].read_text().splitlines()[0])
        self.assertEqual(
            (row["command"], row["outcome"], row["reason_code"]),
            ("graph_readiness", "not_ready", "predecessor_pending"),
        )

    def test_updated_at_stamped_on_transition_and_not_on_refusal(self) -> None:
        """Every progress.json write carries updated_at; a refused transition leaves the bytes untouched."""
        self.save(self.two_node_state())
        self.assertNotIn("updated_at", load(self.path))
        dispatch.begin_wave(self.path)
        stamp = load(self.path)["updated_at"]
        self.assertRegex(stamp, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            dispatch.begin_wave(self.path)  # a wave is already active: refused
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_script_yields_no_json(self) -> None:
        """A nonexistent script produces no JSON at all: a resolution failure a caller can tell apart."""
        result = self.query(str(self.path), "U3[1]", script=ROOT / "hooks/scripts/lib/does_not_exist.py")
        self.assertNotEqual(result.returncode, 0)
        with self.assertRaises(ValueError):
            json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
