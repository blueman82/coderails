"""D4 boundary between standing orders and the memory adapter CLI."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "scripts/lib/memory_adapter.py"


class OrdersAdapterTest(unittest.TestCase):
    """Keep the superseded adapter flag unavailable."""

    def test_standing_orders_render_flag_is_gone(self) -> None:
        """Render rejects the old standing-orders flag."""
        out = subprocess.run(
            [sys.executable, str(ADAPTER), "render", "--standing-orders"], capture_output=True, text=True
        )
        self.assertEqual(out.returncode, 2)
        self.assertIn("unrecognized arguments", out.stderr)

    def test_docs_carry_helper(self) -> None:
        """Both handoff skills name the helper; teardown calls orders.py."""
        for rel in ("skills/handoff/SKILL.md", "packages/codex/skills/handoff/SKILL.md"):
            self.assertIn("memory_adapter.py", (REPO / rel).read_text(), rel)
        self.assertIn("orders.py", (REPO / "skills/agentic-loop/teardown.md").read_text())
