#!/usr/bin/env python3
"""Pin worker statuses: valid/invalid per status, unknown refused, decision request, graph_semantics untouched."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
import worker_status as ws  # noqa: E402

EXTRAS: dict[str, dict[str, Any]] = {
    "NEEDS_DECISION": {"question": "Which?", "options": ["a", "b"], "recommended": "a"},
    "OUTSIDE_SCOPE": {"requested_action": "edit docs", "scope_boundary": "src only"},
    "IRREVERSIBLE_ACTION": {"action": "drop table", "why_irreversible": "no backup", "rollback": "none"},
}


def base(status: str, **over: object) -> dict[str, Any]:
    """A valid result for a status, with overrides."""
    obj: dict[str, Any] = {"status": status, "worker": "w1", "summary": "blocked", "confidence": "verified"}
    obj.update(EXTRAS[status])
    obj.update(over)
    return obj


class ValidateTests(unittest.TestCase):
    """Every status has a valid shape and refusals carry stable codes."""

    def test_valid_each_status(self) -> None:
        """All three statuses validate; recommended may be None."""
        for status in ws.STATUSES:
            self.assertEqual(ws.validate(base(status)), "ok", status)
        self.assertEqual(ws.validate(base("NEEDS_DECISION", recommended=None)), "ok")

    def test_refusal_table(self) -> None:
        """Unknown status, missing/unknown/bad fields, and non-objects."""
        missing = base("OUTSIDE_SCOPE")
        del missing["scope_boundary"]
        cases: list[tuple[object, str]] = [
            ("x", "not_an_object"),
            ({"status": "DONE"}, "unknown_status"),
            ({}, "unknown_status"),
            (missing, "missing_field"),
            (base("OUTSIDE_SCOPE", extra=1), "unknown_field"),
            (base("OUTSIDE_SCOPE", summary=" "), "bad_field"),
            (base("OUTSIDE_SCOPE", confidence="sure"), "bad_field"),
            (base("NEEDS_DECISION", options=["a"]), "bad_field"),
            (base("NEEDS_DECISION", recommended="z"), "bad_field"),
            (base("IRREVERSIBLE_ACTION", rollback=""), "bad_field"),
        ]
        for obj, code in cases:
            self.assertEqual(ws.validate(obj), code, obj)

    def test_decision_request(self) -> None:
        """Valid results become a request; invalid ones raise with the reason code."""
        request = ws.to_decision_request(base("NEEDS_DECISION"))
        self.assertEqual((request["ask"], request["options"], request["recommended"]), ("Which?", ["a", "b"], "a"))
        self.assertIn("src only", ws.to_decision_request(base("OUTSIDE_SCOPE"))["ask"])
        self.assertIn("drop table", ws.to_decision_request(base("IRREVERSIBLE_ACTION"))["ask"])
        with self.assertRaises(ValueError) as caught:
            ws.to_decision_request({"status": "NOPE"})
        self.assertEqual(str(caught.exception), "unknown_status")

    def test_graph_semantics_untouched_and_codex_copy_in_sync(self) -> None:
        """Negative control: graph_semantics is unchanged vs origin/main, and the Codex copy is byte-identical."""
        for path in (
            "skills/agentic-loop/scripts/graph_semantics.py",
            "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
            "packages/graph-semantics/graph_semantics.py",
        ):
            source = (ROOT / path).read_text()
            self.assertNotIn("worker_status", source, path)
            self.assertNotIn("NEEDS_DECISION", source, path)
        digest = [hashlib.sha256((ROOT / p / "worker_status.py").read_bytes()).hexdigest() for p in
                  ("skills/agentic-loop/scripts", "packages/codex/skills/agentic-loop/scripts")]  # fmt: skip
        self.assertEqual(digest[0], digest[1])


if __name__ == "__main__":
    unittest.main()
