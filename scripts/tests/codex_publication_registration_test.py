"""Keep the Codex publication check ahead of the final action-authority hook."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def valid_order(names: list[str]) -> bool:
    """Keep publication immediately before the final authority check."""
    return names[-2:] == ["pr_publication_gate.py", "action_authority_gate.py"]


class CodexPublicationRegistrationTests(unittest.TestCase):
    """Verify the installed Codex hook order and its reversed negative control."""

    def test_publication_gate_precedes_final_authority_gate(self) -> None:
        """A reversed pair must fail the same order condition."""
        groups = json.loads((ROOT / "packages/codex/hooks/hooks.json").read_text())["hooks"]["PreToolUse"]
        bash = next(group for group in groups if group["matcher"] == "^Bash$")
        names = [Path(item["command"].strip('"')).name for item in bash["hooks"]]
        self.assertTrue(valid_order(names))
        reversed_names = names[:-2] + list(reversed(names[-2:]))
        self.assertFalse(valid_order(reversed_names))


if __name__ == "__main__":
    unittest.main()
