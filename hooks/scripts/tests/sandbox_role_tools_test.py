"""Guarded driver roles expose only their fixed capability server without running a model."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.capability_profiles import load_profiles
from scripts.lib.capability_validation import guarded_roles
from scripts.lib.capability_validation import role_tools as profile_tools
from scripts.sandbox.role_tools import role_isolation, role_tools

ROOT = Path(__file__).resolve().parents[3]


class RoleIsolationTests(unittest.TestCase):
    """Inspect real options and ask the selected stdio server for its actual tools."""

    def test_every_guarded_role_loads_only_its_profile(self) -> None:
        """Foreign MCP configs and built-ins have no entry in the explicit launch pool."""
        profiles = load_profiles(ROOT)
        for role in guarded_roles(profiles):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temporary:
                allowed, _ = role_tools(role)
                options = role_isolation(role, allowed)
                servers = json.loads(options[options.index("--mcp-config") + 1])["mcpServers"]
                self.assertEqual(list(servers), [f"plugin_coderails_cap-{role}"])
                server = next(iter(servers.values()))
                messages: list[dict[str, Any]] = [
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "foreign_tool", "arguments": {}},
                    },
                ]
                home = Path(temporary)
                (home / "workflow.config.yaml").write_text("memory:\n  backend: off\n")
                environment = {
                    "HOME": temporary,
                    "PATH": os.path.dirname(sys.executable),
                    "CLAUDE_AGENTIC_LOOP_DIR": temporary,
                    "CLAUDE_SESSION_ID": "inert-role",
                }
                result = subprocess.run(
                    [server["command"], *server["args"]],
                    cwd=home,
                    env=environment,
                    input="".join(json.dumps(row) + "\n" for row in messages),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = [json.loads(line) for line in result.stdout.splitlines()]
                actual = {tool["name"] for tool in rows[0]["result"]["tools"]}
                expected = {tool.replace(".", "_") for tool in profile_tools(profiles["agents"][role])}
                self.assertEqual(actual, expected)
                self.assertEqual(rows[1]["error"]["code"], -32602)
                self.assertEqual(options[options.index("--tools") + 1], "")
                self.assertIn("--strict-mcp-config", options)

    def test_guarded_frontmatter_cannot_expand_the_profile(self) -> None:
        """A wrong-role MCP name is refused before a process starts."""
        allowed, _ = role_tools("security-reviewer")
        with self.assertRaisesRegex(ValueError, "capability profile"):
            role_isolation("security-reviewer", allowed + ", mcp__foreign__cmd_run")

    def test_ordinary_worker_keeps_its_existing_tool_pool(self) -> None:
        """Implementation workers do not receive the guarded-role restriction."""
        allowed, _ = role_tools("loop-worker")
        self.assertEqual(role_isolation("loop-worker", allowed), [])

    def test_incomplete_policy_cannot_turn_a_guarded_role_into_a_worker(self) -> None:
        """Missing, empty or contradictory grants must never restore default CLI tools."""
        allowed, _ = role_tools("security-reviewer")
        for grants in (None, [], ["shell.raw"], ["worktree.write"]):
            profiles = load_profiles(ROOT)
            if grants is None:
                profiles["agents"].pop("security-reviewer")
            else:
                profiles["agents"]["security-reviewer"] = grants
            with (
                self.subTest(grants=grants),
                patch("scripts.sandbox.role_tools.load_profiles", return_value=profiles),
                self.assertRaisesRegex(ValueError, "capability policy"),
            ):
                role_isolation("security-reviewer", allowed)


if __name__ == "__main__":
    unittest.main()
