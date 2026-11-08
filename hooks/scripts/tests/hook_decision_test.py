"""A hook trace keeps a typed decision without changing its original fields."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import hook_decision  # noqa: E402
from hooks.scripts.lib.trace_row import append_hook_row as append_row  # noqa: E402


class HookDecisionTests(unittest.TestCase):
    """Keep trace records typed, content-free, and fail-open."""

    def setUp(self) -> None:
        """Use a small catalog and trace directory."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name)
        self.catalog = self.base / "messages.json"
        self.catalog.write_text(
            json.dumps(
                {
                    "hooks": {
                        "autonomous_gate": {"reason_code": "authority_deny", "remediation": "Revoke the authority."}
                    },
                    "aliases": {"autonomous": "autonomous_gate"},
                    "reasons": {"stop_row_missing": {"remediation": "Record the current Stop result."}},
                    "fallback": {"remediation": "Read the hook reason."},
                }
            )
        )

    def test_record_uses_actual_reason_and_catalog_remediation(self) -> None:
        """An alias selects recovery text without replacing the emitted reason."""
        with patch.object(hook_decision, "CATALOG", self.catalog):
            record = hook_decision.make_record("autonomous", "blocked", "crack_on_legacy_flag", {"cmd": "abc"})
        self.assertEqual(
            record,
            {
                "hook": "autonomous",
                "decision": "blocked",
                "reason_code": "crack_on_legacy_flag",
                "params": {"cmd": "abc"},
                "remediation": "Revoke the authority.",
            },
        )

    def test_exact_reason_precedes_hook_action(self) -> None:
        """The emitted reason gives a more specific action than the hook name."""
        with patch.object(hook_decision, "CATALOG", self.catalog):
            record = hook_decision.make_record("autonomous", "blocked", "stop_row_missing")
        self.assertEqual(record["reason_code"], "stop_row_missing")
        self.assertEqual(record["remediation"], "Record the current Stop result.")

    def test_unknown_dynamic_reason_has_static_fallback(self) -> None:
        """An unknown hook and reason still give a stable recovery step."""
        with patch.object(hook_decision, "CATALOG", self.catalog):
            record = hook_decision.make_record("graph.inspect", "refused", "bad_state")
        self.assertEqual(record["remediation"], hook_decision.FALLBACK_REMEDIATION)

    def test_invalid_required_field_refuses(self) -> None:
        """The typed record builder rejects missing or non-text fields."""
        with patch.object(hook_decision, "CATALOG", self.catalog):
            for field in ("", " ", None, True):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    hook_decision.make_record(field, "blocked", "reason")

    def test_unknown_decision_refuses_emission(self) -> None:
        """Unknown decisions cannot be recorded as typed hook results."""
        with self.assertRaises(ValueError):
            hook_decision.make_record("gate", "made_up_decision", "reason")
        self.assertFalse(append_row("gate", "made_up_decision", "reason", "session", base=self.base))
        self.assertFalse((self.base / "session" / "trace.jsonl").exists())

    def test_trace_adds_record_without_raw_params(self) -> None:
        """The nested record reuses hashes rather than storing source text."""
        with patch.object(hook_decision, "CATALOG", self.catalog):
            self.assertTrue(
                append_row(
                    "autonomous", "blocked", "authority_deny", "session", inputs={"cmd": "SECRET"}, base=self.base
                )
            )
        raw = (self.base / "session" / "trace.jsonl").read_text()
        self.assertNotIn("SECRET", raw)
        row = json.loads(raw)
        expected = hashlib.sha256(b"SECRET").hexdigest()
        self.assertEqual(row["inputs"], {"cmd": expected})
        self.assertEqual(row["decision_record"]["params"], {"cmd": expected})
        self.assertEqual(row["decision_record"]["reason_code"], "authority_deny")

    def test_bad_catalog_does_not_break_trace(self) -> None:
        """A catalog failure still leaves a typed record with the emitted reason."""
        self.catalog.write_text("{")
        with patch.object(hook_decision, "CATALOG", self.catalog):
            self.assertTrue(append_row("gate", "blocked", "reason", "session", base=self.base))
        row = json.loads((self.base / "session" / "trace.jsonl").read_text())
        self.assertEqual(row["decision_record"]["reason_code"], "reason")
        self.assertEqual(row["decision_record"]["remediation"], hook_decision.FALLBACK_REMEDIATION)

    def test_absent_catalog_keeps_typed_record(self) -> None:
        """A missing catalog cannot remove required trace fields."""
        with patch.object(hook_decision, "CATALOG", self.base / "absent.json"):
            self.assertTrue(append_row("gate", "blocked", "reason", "session", base=self.base))
        row = json.loads((self.base / "session" / "trace.jsonl").read_text())
        self.assertEqual(row["decision_record"]["hook"], "gate")
        self.assertEqual(row["decision_record"]["remediation"], hook_decision.FALLBACK_REMEDIATION)


if __name__ == "__main__":
    unittest.main()
