"""`add-unit` contract flags are stored identically by both providers and reach the begin-wave contract."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
import graph_contract

from packages.tests.test_provider_controller_commands import ControllerCase


class AddUnitContractTests(ControllerCase):
    """Only flags actually given are stored; a bad model role is a coded refusal that changes nothing."""

    def test_flags_are_stored_and_defaults_are_not(self) -> None:
        """--model-role, --write-scope, --lesson and --scope land on work_units[u]; absent flags add no keys."""
        for c in self.each():
            c.start()
            self.assertEqual(c.add("1").returncode, 0)
            result = c.add(
                "2",
                "--manifest",
                "src/**",
                "--model-role",
                "frontier",
                "--write-scope",
                "src/a.py",
                "--write-scope",
                "src/b.py",
                "--lesson",
                "read the spec",
                "--scope",
                "unit two",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                c.read()["work_units"],
                {
                    "1": {"status": "pending"},
                    "2": {
                        "status": "pending",
                        "manifest": ["src/**"],
                        "model_role": "frontier",
                        "write_scope": ["src/a.py", "src/b.py"],
                        "lessons": ["read the spec"],
                        "scope": "unit two",
                    },
                },
            )

    def test_bad_model_role_is_refused_with_a_code_and_no_write(self) -> None:
        """A model role outside the closed enum is refused before the lock, traced, and the state is untouched."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            result = c.add("1", "--model-role", "huge")
            self.refused(result, "add_unit_refused_bad_field")
            self.assertEqual(c.path.read_bytes(), before)
            self.assertEqual(c.codes("add-unit"), ["add_unit_refused_bad_field"])

    def test_stored_inputs_and_defaults_reach_the_begin_wave_contract(self) -> None:
        """begin-wave renders the unit's inputs; unset inputs take the documented defaults (write_scope = manifest)."""
        for c in self.each():
            c.start()
            self.assertEqual(c.add("1", "--manifest", "src/**", "--lesson", "L1").returncode, 0)
            contract = graph_contract.build_contract(c.read(), "U3[1]", "main")
            self.assertEqual(
                (contract["role"], contract["manifest"], contract["write_scope"], contract["lessons"]),
                ("loop-worker", ["src/**"], ["src/**"], ["L1"]),
            )
            defaults = (contract["model_role"], contract["scope"], contract["disposition"])
            self.assertEqual(defaults, ("default", "", None))


if __name__ == "__main__":
    unittest.main()
