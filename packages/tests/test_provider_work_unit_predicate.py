"""The work_units completion predicate must agree across providers (plan section 13)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))
from graph_completion import validate_work_units as codex_predicate  # noqa: E402
from graph_identity import GraphError  # noqa: E402

from hooks.scripts.lib.loop_completion import validate_work_units as claude_predicate  # noqa: E402

PASSING: dict[str, Any] = {
    "missing": {},
    "null": {"work_units": None},
    "empty object": {"work_units": {}},
    "done": {"work_units": {"1": {"status": "done"}}},
    "dropped with reason": {"work_units": {"1": {"status": "dropped", "dropped_reason": "out of scope"}}},
    "mixed done and dropped": {
        "work_units": {"1": {"status": "done"}, "2": {"status": "dropped", "dropped_reason": "superseded"}}
    },
}
BLOCKING: dict[str, Any] = {
    "pending": {"work_units": {"1": {"status": "pending"}}},
    "in-progress": {"work_units": {"1": {"status": "in-progress"}}},
    "blocked": {"work_units": {"1": {"status": "blocked"}}},
    "dropped without reason": {"work_units": {"1": {"status": "dropped"}}},
    "dropped blank reason": {"work_units": {"1": {"status": "dropped", "dropped_reason": "   "}}},
    "dropped non-string reason": {"work_units": {"1": {"status": "dropped", "dropped_reason": 7}}},
    "unknown status": {"work_units": {"1": {"status": "finished"}}},
    "missing status": {"work_units": {"1": {}}},
    "non-object entry": {"work_units": {"1": "done"}},
    "array container": {"work_units": [{"status": "done"}]},
    "string container": {"work_units": "done"},
    "blank id": {"work_units": {"": {"status": "done"}}},
    "whitespace id": {"work_units": {"  ": {"status": "done"}}},
    "one unfinished among done": {"work_units": {"1": {"status": "done"}, "2": {"status": "pending"}}},
}


class WorkUnitPredicateTests(unittest.TestCase):
    """Missing, null and empty pass; any other non-done, non-reasoned-dropped entry blocks, on both providers."""

    def test_passing_states_pass_on_both_providers(self) -> None:
        """Absent, null, empty, done and reasoned-dropped work units never block completion."""
        for name, state in PASSING.items():
            with self.subTest(case=name):
                claude_predicate(dict(state))
                codex_predicate(dict(state))

    def test_malformed_or_unfinished_states_block_on_both_providers(self) -> None:
        """Every malformed or non-terminal shape is refused by both predicates, never one alone."""
        for name, state in BLOCKING.items():
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    claude_predicate(dict(state))
                with self.assertRaises(GraphError):
                    codex_predicate(dict(state))


if __name__ == "__main__":
    unittest.main()
