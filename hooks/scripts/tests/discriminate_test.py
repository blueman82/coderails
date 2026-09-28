"""Preserve freeze-time fixture discrimination, environmental and diagnostic controls."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.artifact_io import JsonObject
from scripts.lib.eval_validation import validate_discriminating, validate_structure

ROOT = Path(__file__).resolve().parents[3]
BROKEN = "awk -F'[ /]' '/suites passed/ {found=1; ok=($(NF-3) == $(NF-2))} END {exit (found && ok) ? 0 : 1}'"
REPAIRED = (
    'awk \'/suites passed/ {found=1; split($3,a,"/"); ok=(a[1]==a[2] && a[1]>0)} ' "END {exit (found && ok) ? 0 : 1}'"
)


def item(formula: str = "grep -q x", good: str = "x", bad: str = "y") -> JsonObject:
    """Create one complete scripted fixture with explicit pass and fail inputs."""
    return {
        "id": "e1",
        "priority": "P0",
        "mode": "scripted",
        "status": "pass",
        "cmd": "unused | " + formula,
        "negative_control": "false",
        "evidence": "log",
        "fixtures": {"good": good, "bad": bad, "formula": formula},
    }


class DiscriminateTests(unittest.TestCase):
    """Exercise every legacy discrimination case without repository mutations."""

    def evaluate(self, entries: list[JsonObject]) -> None:
        """Write one temporary eval suite and run the production validator."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evals.json"
            path.write_text(json.dumps({"verification_level": 1, "evals": entries}))
            validate_discriminating(path)

    def test_original_broken_awk_and_repair(self) -> None:
        """Broken numerator extraction names the eval and shared failure status."""
        good, bad = "--- run_all: 39/39 suites passed ---", "--- run_all: 18/40 suites passed ---"
        with self.assertRaisesRegex(ValueError, "e1.*non-discriminating.*both exit 1"):
            self.evaluate([item(BROKEN, good, bad)])
        self.evaluate([item(REPAIRED, good, bad)])
        with self.assertRaisesRegex(ValueError, "e1.*non-discriminating.*both exit 0"):
            self.evaluate([item("cat")])

    def test_derivation_and_explicit_override(self) -> None:
        """Allow absent fixtures, derive from the last pipe, and honor explicit formulas."""
        absent = item()
        absent.pop("fixtures")
        self.evaluate([absent])
        derived = item()
        derived["fixtures"] = {"good": "x", "bad": "y"}
        self.evaluate([derived])
        derived["cmd"] = "no pipe"
        with self.assertRaisesRegex(ValueError, "fixtures.formula"):
            self.evaluate([derived])
        derived["fixtures"] = {"good": "x", "bad": "y", "formula": "grep -q x"}
        self.evaluate([derived])

    def test_all_entries_and_required_shapes(self) -> None:
        """Inspect later evals and refuse missing fixtures rather than inventing empty inputs."""
        later = item("cat")
        later["id"] = "e2"
        with self.assertRaisesRegex(ValueError, "e2.*non-discriminating"):
            self.evaluate([item(), later])
        for fixtures in ({"good": "x", "formula": "grep -q x"}, {"bad": "y", "formula": "! grep -q y"}):
            entry = item()
            entry["fixtures"] = fixtures
            with self.assertRaisesRegex(ValueError, "e1"):
                self.evaluate([entry])
        malformed = item()
        malformed["fixtures"] = "malformed"
        with self.assertRaisesRegex(ValueError, "e1.*object"):
            self.evaluate([malformed])

    def test_environment_and_inversion_are_distinct(self) -> None:
        """Separate content inversion from command lookup, permission and signal failures."""
        with self.assertRaises(ValueError) as caught:
            self.evaluate([item("grep -q y")])
        self.assertNotIn("non-discriminating", str(caught.exception))
        self.assertIn("e1", str(caught.exception))
        for formula in (
            "coderails_nonexistent_fixture_command",
            "if grep -q x; then exit 0; else exit 126; fi",
            "if grep -q x; then exit 0; else kill -9 $$; fi",
        ):
            with self.assertRaises(ValueError) as caught:
                self.evaluate([item(formula)])
            self.assertNotIn("non-discriminating", str(caught.exception))
            self.assertIn("e1", str(caught.exception))
        with (
            patch("scripts.lib.eval_validation.run_recorded", return_value=(142, "")),
            self.assertRaisesRegex(ValueError, "timed out"),
        ):
            self.evaluate([item()])

    def test_structure_still_requires_negative_control(self) -> None:
        """Optional fixture data cannot bypass the required scripted negative control."""
        entry = item()
        entry["negative_control"] = ""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evals.json"
            path.write_text(
                json.dumps(
                    {
                        "verification_level": 1,
                        "verification_justification": "fixture",
                        "head_sha": "a" * 40,
                        "evals": [entry],
                    }
                )
            )
            with self.assertRaisesRegex(ValueError, "negative_control"):
                validate_structure(path)

    def test_cli_dispatch_and_usage(self) -> None:
        """Expose the discrimination operation through the public Python CLI."""
        command = [sys.executable, str(ROOT / "scripts/post_evals.py")]
        usage = subprocess.run(command + ["--help"], capture_output=True, text=True)
        self.assertIn("validate-discriminating", usage.stdout)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evals.json"
            path.write_text(json.dumps({"verification_level": 1, "evals": [item()]}))
            result = subprocess.run(command + ["validate-discriminating", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
