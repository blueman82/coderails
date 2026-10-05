"""The Phase 0 closure matrix data must be complete and its generated md fresh."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import closure_matrix as cm  # noqa: E402

DATA = json.loads(cm.DATA.read_text())


class ClosureMatrixTest(unittest.TestCase):
    """The closure data is complete, the md is fresh, and mutated data is rejected."""

    def test_data_is_complete(self) -> None:
        """The checked-in data has no validation problems."""
        self.assertEqual(cm.validate(DATA), [])

    def test_exactly_the_24_inventory_rows(self) -> None:
        """Ids are exactly 1-23 plus 5a."""
        self.assertEqual(sorted(r["id"] for r in DATA["rows"]), sorted(cm.ROW_IDS))

    def test_gap1_is_the_opt_in_exception(self) -> None:
        """Gap1 is mapped only as the opt-in integrity-gate exception."""
        gap1 = next(g for g in DATA["gaps"] if g["id"] == "gap1")
        self.assertIn("opt-in", gap1["exception"])
        self.assertIn("INTEGRITY-GATE", gap1["exception"])

    def test_generated_md_is_fresh(self) -> None:
        """The md equals what the generator renders from the data."""
        self.assertEqual(cm.MD.read_text(), cm.render(DATA), "run scripts/closure_matrix.py")

    def test_stale_md_is_detected(self) -> None:
        """Changing the data changes the render, so a stale md would differ."""
        mutated = copy.deepcopy(DATA)
        mutated["rows"][0]["acceptance_test"] += " changed"
        self.assertNotEqual(cm.MD.read_text(), cm.render(mutated))

    # Negative controls: a mutated copy of the data must be rejected.
    def test_rejects_dropped_row(self) -> None:
        """Dropping a row is rejected."""
        m = copy.deepcopy(DATA)
        m["rows"] = [r for r in m["rows"] if r["id"] != "5a"]
        self.assertIn("row 5a missing", cm.validate(m))

    def test_rejects_blank_acceptance_test(self) -> None:
        """A blank acceptance_test is rejected."""
        m = copy.deepcopy(DATA)
        m["rows"][3]["acceptance_test"] = "  "
        self.assertTrue(any("empty acceptance_test" in e for e in cm.validate(m)))

    def test_rejects_missing_phase(self) -> None:
        """A row without a phase is rejected."""
        m = copy.deepcopy(DATA)
        del m["rows"][0]["phase"]
        self.assertTrue(any("no phase" in e for e in cm.validate(m)))

    def test_rejects_deleted_gap(self) -> None:
        """A deleted gap is rejected."""
        m = copy.deepcopy(DATA)
        m["gaps"] = [g for g in m["gaps"] if g["id"] != "gap4"]
        self.assertIn("gap4 missing", cm.validate(m))

    def test_rejects_unmapped_gap(self) -> None:
        """A gap without a phase is rejected."""
        m = copy.deepcopy(DATA)
        next(g for g in m["gaps"] if g["id"] == "gap2").pop("phase")
        self.assertIn("gap2 is unmapped (no phase 1-6)", cm.validate(m))

    def test_rejects_gap1_without_exception(self) -> None:
        """Gap1 without its exception is rejected."""
        m = copy.deepcopy(DATA)
        next(g for g in m["gaps"] if g["id"] == "gap1").pop("exception")
        self.assertTrue(any("gap1" in e for e in cm.validate(m)))

    def _bad(self, mutate: Callable[[dict[str, Any]], object], needle: str) -> None:
        m = copy.deepcopy(DATA)
        mutate(m)
        self.assertTrue(any(needle in e for e in cm.validate(m)), cm.validate(m))

    def test_rejects_wrong_types(self) -> None:
        """Null/non-string text and bool or out-of-range phases are rejected."""
        self._bad(lambda m: m["rows"][0].update(acceptance_test=None), "empty acceptance_test")
        self._bad(lambda m: m["rows"][0].update(acceptance_test=[]), "empty acceptance_test")
        self._bad(lambda m: m["rows"][0].update(phase=True), "no phase")
        self._bad(lambda m: m["rows"][0].update(phase=7), "no phase")
        self._bad(lambda m: m["gaps"][1].update(phase=99), "gap2 is unmapped")
        self._bad(lambda m: m["gaps"][1].update(phase=True), "gap2 is unmapped")
        self._bad(lambda m: m["gaps"][0].update(exception=None), "gap1 has no exception")
        self._bad(lambda m: m["gaps"][0].update(exception="something else"), "gap1 has no exception")

    def test_rejects_duplicate_and_extra_ids(self) -> None:
        """Duplicate or unexpected row and gap ids are rejected."""
        self._bad(lambda m: m["rows"].append(copy.deepcopy(m["rows"][0])), "duplicated")
        self._bad(lambda m: m["rows"].append({**m["rows"][0], "id": "99"}), "unexpected")
        self._bad(lambda m: m["gaps"].append({**m["gaps"][1], "id": "gap6"}), "unexpected")
        self._bad(lambda m: m["gaps"].append(copy.deepcopy(m["gaps"][1])), "duplicated")
        self._bad(lambda m: m["rows"].append("junk"), "not an object")

    def test_rejects_wrong_phase_map(self) -> None:
        """A row or gap moved to a different valid phase is rejected."""
        self._bad(lambda m: m["rows"][0].update(phase=4), "plan says 2")
        self._bad(lambda m: m["gaps"][1].update(phase=5), "gap2 is in phase 5, plan says 3")

    def test_blocked_on_is_separate_and_not_blank(self) -> None:
        """Human-decision preconditions live in blocked_on, not in the acceptance text."""
        rows = {r["id"]: r for r in DATA["rows"]}
        for i in ("3", "14"):
            self.assertTrue(rows[i]["blocked_on"].strip())
            self.assertNotIn("after the", rows[i]["acceptance_test"])
        self._bad(lambda m: m["rows"][2].update(blocked_on=" "), "empty blocked_on")

    def test_rejects_blank_required_fields(self) -> None:
        """Blank or missing defect, refs, record, status and gap title are rejected."""

        def drop_row_key(k: str) -> Callable[[dict[str, Any]], object]:
            return lambda m: m["rows"][2].pop(k)

        def blank_gap_key(k: str) -> Callable[[dict[str, Any]], object]:
            return lambda m: m["gaps"][2].update({k: " "})

        for k in cm.ROW_STR:
            self._bad(drop_row_key(k), f"empty {k}")
        for k in cm.GAP_STR:
            self._bad(blank_gap_key(k), f"empty {k}")


if __name__ == "__main__":
    unittest.main()
