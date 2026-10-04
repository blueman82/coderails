#!/usr/bin/env python3
"""Preserve the original confidence and verification response corpora in Python."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).with_name("fixtures") / "discipline_responses"


class DisciplineResponseTests(unittest.TestCase):
    """Check Stop, SubagentStop, headless scope, advisory demotion, and turn-local evidence."""

    def test_original_response_corpus(self) -> None:
        """Every original input keeps its exit status and advisory contract (always exit 0)."""
        rows: list[dict[str, Any]] = sorted(
            [row for path in FIXTURES.glob("*.json") for row in json.loads(path.read_text())],
            key=lambda row: row["fixture_index"],
        )
        for index, raw in enumerate(rows):
            with self.subTest(source=raw["source"], index=index), tempfile.TemporaryDirectory() as directory:
                case = json.loads(json.dumps(raw).replace("{sandbox}", directory))
                for name, text in case["files"].items():
                    path = Path(name)
                    self.assertTrue(path.is_relative_to(directory), "fixture must stay inside its private directory")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("CLAUDE_HOOK_") and key != "CODERAILS_HEADLESS_RUN"
                }
                environment.update(case["env"])
                hook = Path(__file__).resolve().parents[1] / f"{case['source']}.py"
                result = subprocess.run(
                    [sys.executable, str(hook)],
                    input=json.dumps(case["request"]),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )
                self.assertEqual(result.returncode, case["returncode"], result.stderr)
                expected: dict[str, Any] = json.loads(case["stdout"]) if case["stdout"].strip() else {}
                actual: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
                if expected:
                    self.assertEqual(
                        actual["hookSpecificOutput"]["hookEventName"], expected["hookSpecificOutput"]["hookEventName"]
                    )
                    self.assertIn("[discipline-advisory]", actual["hookSpecificOutput"]["additionalContext"])
                else:
                    self.assertEqual(actual, {})
                self.assertEqual(result.stderr, "", "a demoted lint must not write a block message")
        self.assertEqual(len(rows), 80)


if __name__ == "__main__":
    unittest.main()
