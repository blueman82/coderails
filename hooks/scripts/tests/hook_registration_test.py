#!/usr/bin/env python3
"""Pin lifecycle wiring, native entrypoints, timeout floor, and the documented enforcement ceiling."""

from __future__ import annotations

import json
import shlex
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class HookRegistrationTests(unittest.TestCase):
    """Registration must preserve behavior without retaining retired shell execution paths."""

    def test_python_entrypoints_and_timeout_floor(self) -> None:
        """Every registered executable exists and its outer timeout covers the five-second reader."""
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
        for event, groups in hooks.items():
            for group in groups:
                for item in group["hooks"]:
                    with self.subTest(event=event, command=item["command"]):
                        arguments = shlex.split(item["command"].replace("${CLAUDE_PLUGIN_ROOT}", str(ROOT)))
                        self.assertTrue(arguments[-1].endswith(".py"))
                        self.assertNotIn("bash", arguments)
                        self.assertGreaterEqual(item.get("timeout", 60), 5)
                        self.assertTrue(Path(arguments[-1]).is_file())
        source = (ROOT / "hooks/scripts/hook_common.py").read_text()
        self.assertIn("timeout_seconds: float = 5.0", source)
        self.assertIn("select.select", source)
        self.assertIn("os.read", source)
        self.assertNotIn("sys.stdin.read()", source)

    def test_prose_gate_retired(self) -> None:
        """Negative control: crack-on denial is the authority-backed AskUserQuestion gate only; no Stop prose gate."""
        self.assertNotIn("crack_on_prose_gate", (ROOT / "hooks/hooks.json").read_text())
        self.assertFalse((ROOT / "hooks/scripts/crack_on_prose_gate.py").exists())

    def test_event_order_and_scoping(self) -> None:
        """Prompt registration stays minimal and headless exemptions stay Stop-only."""
        hooks = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]
        self.assertEqual(len(hooks["UserPromptSubmit"]), 1)
        prompt = hooks["UserPromptSubmit"][0]["hooks"]
        self.assertEqual(len(prompt), 2)
        self.assertIn("inject_context.py", prompt[0]["command"])
        self.assertIn("crack_on_gate.py", prompt[1]["command"])
        stop = hooks["Stop"][0]["hooks"]
        self.assertIn("voice_announce.py", stop[0]["command"])
        self.assertIn("offload_push_guard.py", stop[-1]["command"])
        subagent = " ".join(item["command"] for group in hooks["SubagentStop"] for item in group["hooks"])
        for name in ("check_confidence_labels", "check_verify_loop", "offload_push_guard"):
            self.assertIn(name, subagent)
        self.assertNotIn("loop_state_guard", subagent)
        self.assertNotIn("loop_stall_guard", subagent)

    def test_manifest_versions_and_honest_ceiling(self) -> None:
        """Version synchronization and the invocation-only boundary cannot disappear silently."""
        plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text())["version"]
        marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())["plugins"][0]["version"]
        self.assertIsInstance(plugin, str)
        self.assertTrue(plugin)
        self.assertEqual(plugin, marketplace)
        guide = (ROOT / "AGENTS.md").read_text().lower()
        for phrase in ("redirect-and-audit layer", "branch protection", "invocation"):
            self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
