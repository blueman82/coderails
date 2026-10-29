"""Registration and executable modes for the Codex publication hook."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "packages/codex/hooks/scripts/pr_publication_gate.py"


class RegistrationTests(unittest.TestCase):
    """The hook is shipped, executable and registered under the Bash matcher."""

    def test_registered_and_executable(self) -> None:
        """hooks.json lists the hook under ^Bash$ and the file is executable."""
        data = json.loads((ROOT / "packages/codex/hooks/hooks.json").read_text())["hooks"]["PreToolUse"]
        commands = [h["command"] for group in data if group["matcher"] == "^Bash$" for h in group["hooks"]]
        self.assertIn('"${PLUGIN_ROOT}/hooks/scripts/pr_publication_gate.py"', commands)
        self.assertTrue(os.access(HOOK, os.X_OK))

    def test_entrypoint_mode_fixture(self) -> None:
        """python_entrypoint_modes records the new hook as executable."""
        modes = json.loads((ROOT / "hooks/scripts/tests/fixtures/python_entrypoint_modes.json").read_text())
        self.assertEqual(modes.get("packages/codex/hooks/scripts/pr_publication_gate.py"), "100755")
        self.assertEqual(modes.get("scripts/lib/publication_gate.py"), "100644")
        self.assertEqual(modes.get("packages/codex/scripts/lib/publication_gate.py"), "100644")


if __name__ == "__main__":
    unittest.main()
