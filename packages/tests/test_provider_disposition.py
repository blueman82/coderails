"""`add-unit --disposition` and `disposition-audit` behave identically through both providers' real CLIs."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))
import graph_completion  # noqa: E402
import graph_contract  # noqa: E402
import graph_vocab  # noqa: E402
from graph_identity import GraphError  # noqa: E402

from hooks.scripts.lib import loop_completion  # noqa: E402
from packages.tests.test_provider_controller_commands import ControllerCase  # noqa: E402

PAIR = ("--named-blocker", "vendor API frozen", "--removal-ticket", "OPS-42")


class AddUnitDispositionTests(ControllerCase):
    """The pair rule is enforced at the writer and again at audit and completion."""

    def test_preserve_compat_needs_both_halves(self) -> None:
        """Missing blocker, missing ticket, blank values: coded refusal, state bytes unchanged."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            for extra in (
                ("--disposition", "preserve-compat"),
                ("--disposition", "preserve-compat", "--named-blocker", "b"),
                ("--disposition", "preserve-compat", "--removal-ticket", "T-1"),
                ("--disposition", "preserve-compat", "--named-blocker", "  ", "--removal-ticket", "T-1"),
                ("--named-blocker", "b"),
            ):
                self.refused(c.add("1", *extra), "add_unit_refused_disposition")
                self.assertEqual(c.path.read_bytes(), before)
            self.assertEqual(c.codes("add-unit"), ["add_unit_refused_disposition"] * 5)

    def test_clean_break_forbids_the_pair(self) -> None:
        """A clean break with a ticket or blocker is refused; a bare clean break is stored."""
        for c in self.each():
            c.start()
            self.refused(
                c.add("1", "--disposition", "clean-break", "--removal-ticket", "T-1"), "add_unit_refused_disposition"
            )
            self.assertEqual(c.add("1", "--disposition", "clean-break").returncode, 0)
            self.assertEqual(c.read()["work_units"]["1"]["disposition"], {"kind": "clean-break"})

    def test_valid_preserve_compat_round_trips_into_the_contract(self) -> None:
        """The stored object is the one the begin-wave contract carries."""
        for c in self.each():
            c.start()
            result = c.add("1", "--disposition", "preserve-compat", *PAIR)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected: dict[str, Any] = {
                "kind": "preserve-compat",
                "named_blocker": "vendor API frozen",
                "removal_ticket": "OPS-42",
            }
            self.assertEqual(c.read()["work_units"]["1"]["disposition"], expected)
            self.assertEqual(graph_contract.build_contract(c.read(), "U3[1]", "main")["disposition"], expected)

    def test_audit_is_zero_for_valid_and_nonzero_for_a_hand_edited_unit(self) -> None:
        """The audit lists units and exits 1 when a preserve-compat unit lost half of its pair."""
        for c in self.each():
            c.start()
            c.add("1", "--disposition", "preserve-compat", *PAIR)
            c.add("2")
            good = c.run("disposition-audit")
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)["offenders"], [])
            state = c.read()
            del state["work_units"]["1"]["disposition"]["removal_ticket"]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            bad = c.run("disposition-audit")
            self.assertEqual(bad.returncode, 1)
            self.assertEqual(json.loads(bad.stdout)["offenders"], ["1"])

    def test_completion_blocks_a_bad_disposition_even_on_a_done_unit(self) -> None:
        """Both providers' work-unit completion gate rejects the hand-edited unit; a valid one passes."""
        valid: dict[str, Any] = {"1": {"status": "done", "disposition": {"kind": "clean-break"}}}
        broken: dict[str, Any] = {"1": {"status": "done", "disposition": {"kind": "preserve-compat"}}}
        loop_completion.validate_work_units({"work_units": valid})
        graph_completion.validate_work_units({"work_units": valid})
        with self.assertRaisesRegex(ValueError, "disposition"):
            loop_completion.validate_work_units({"work_units": broken})
        with self.assertRaisesRegex(GraphError, "disposition"):
            graph_completion.validate_work_units({"work_units": broken})

    def test_vocab_rules(self) -> None:
        """The shared validator: no flags is None, unknown kind refused, offenders found by audit."""
        self.assertIsNone(graph_vocab.validate_disposition(None, None, None))
        with self.assertRaises(ValueError):
            graph_vocab.validate_disposition("fork", None, None)
        self.assertEqual(graph_vocab.disposition_offenders({"1": {"disposition": {"kind": "fork"}}}), ["1"])
        self.assertEqual(graph_vocab.disposition_offenders({"1": {"status": "done"}}), [])


if __name__ == "__main__":
    unittest.main()
