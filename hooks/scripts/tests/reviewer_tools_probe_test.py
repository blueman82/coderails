#!/usr/bin/env python3
"""Probe the real Claude CLI against a loopback API fixture: what tools does a guarded role actually get?

The CLI owns tool assembly, so the oracle is the `tools` array of the request it sends the model, not the agent file.
No billing: the fixture never forwards anything and the credentials are placeholders.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib.capability_profiles import guarded_agents, load_profiles  # noqa: E402
from hooks.scripts.tests.lib.native_api_fixture import NativeAPIFixture  # noqa: E402

PROFILES = load_profiles(ROOT)
ROLES = sorted(guarded_agents(PROFILES))
FORBIDDEN = {"Bash", "Write", "Edit", "NotebookEdit", "Agent", "Task", "Read", "Grep", "Glob", "WebFetch", "MultiEdit"}
CHILD_MARKER = "CHILD_PROBE_MARKER"


def expected(role: str) -> set[str]:
    """The profile-derived MCP names, plus Skill for preflight-scout only."""
    names = {
        f"mcp__plugin_coderails_cap-{role}__{cap.replace('.', '_')}"
        for cap in PROFILES["agents"][role]
        if cap in {"repo.inspect", "diff.read", "tests.run", "pr.comment", "cmd.run"}
    }
    return names | ({"Skill"} if role == "preflight-scout" else set())


class RecordingFixture(NativeAPIFixture):
    """Record every request body; answer with plain text, or one Agent dispatch on the first parent turn."""

    def __init__(self, dispatch_role: str | None) -> None:
        """`dispatch_role` makes the first parent turn call Agent(subagent_type=coderails:<role>)."""
        self.bodies: list[dict[str, Any]] = []
        self.dispatch_role = dispatch_role
        super().__init__(lambda: [])

    def respond(self, body: dict[str, Any]) -> dict[str, Any]:
        """Store the body, then reply deterministically."""
        self.bodies.append(body)
        first = json.dumps(body.get("messages", [])[:1])
        history = json.dumps(body.get("messages", []))
        blocks: list[dict[str, Any]] = [{"type": "text", "text": "PROBE_DONE"}]
        if self.dispatch_role and CHILD_MARKER not in first and "toolu_probe_1" not in history:
            blocks = [
                {
                    "type": "tool_use",
                    "id": "toolu_probe_1",
                    "name": "Agent",
                    "input": {
                        "subagent_type": f"coderails:{self.dispatch_role}",
                        "description": "probe",
                        "prompt": CHILD_MARKER,
                    },
                }
            ]
        return {
            "id": "msg_probe",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": blocks,
            "stop_reason": "tool_use" if blocks[0]["type"] == "tool_use" else "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    def child_tools(self) -> list[str] | None:
        """Tool names of the request whose first message is the dispatched child's prompt."""
        for body in self.bodies:
            if body.get("tools") and CHILD_MARKER in json.dumps(body.get("messages", [])[:1]):
                return [t["name"] for t in body.get("tools", [])]
        return None

    def parent_tools(self) -> list[str]:
        """Tool names of the first request (the session's own agent)."""
        return [t["name"] for t in self.bodies[0].get("tools", [])]


@unittest.skipUnless(shutil.which("claude"), "real Claude CLI is required for the tool-binding probe")
class ReviewerToolsProbeTest(unittest.TestCase):
    """Two routes to the same guarantee: --agent sessions and Agent-tool dispatch."""

    def run_cli(self, fixture: RecordingFixture, *extra: str) -> subprocess.CompletedProcess[str]:
        """Run the CLI once against the fixture in a private HOME with the repo loaded as the plugin."""
        with tempfile.TemporaryDirectory(prefix="coderails-tools-probe-") as home:
            env = dict(os.environ)
            for key in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
                env.pop(key, None)
            env.update(
                HOME=home,
                CLAUDE_CONFIG_DIR=f"{home}/.claude",
                CLAUDE_AGENTIC_LOOP_DIR=f"{home}/loops",
                ANTHROPIC_API_KEY="local-fixture-not-a-credential",
                ANTHROPIC_AUTH_TOKEN="local-fixture-not-a-credential",
                ANTHROPIC_BASE_URL=fixture.url,
                CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            )
            args = ["claude", "--plugin-dir", str(ROOT), "--permission-mode", "bypassPermissions", *extra]
            args += ["--model", "sonnet", "-p", "probe"]
            done = subprocess.run(args, cwd=home, env=env, capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:] + done.stdout[-500:])
        self.assertFalse(fixture.errors, fixture.errors)
        return done

    def assert_bound(self, role: str, tools: list[str] | None, route: str) -> None:
        """Exactly the profile-derived tools, no shell, no edit tool, no native read tool, no nested agents."""
        self.assertIsNotNone(tools, f"{route}: no request carried the {role} prompt")
        assert tools is not None
        self.assertEqual(sorted(tools), sorted(expected(role)), f"{route} {role}")
        self.assertEqual(FORBIDDEN & set(tools), set(), f"{route} {role}")
        self.assertTrue(all(len(name) <= 64 for name in tools))

    def test_agent_session_has_only_its_mcp_tools(self) -> None:
        """`claude --agent coderails:<role>`: the reviewer session has no shell (the tools array lists none)."""
        for role in ROLES:
            with self.subTest(role=role):
                fixture = RecordingFixture(None)
                self.addCleanup(fixture.close)
                self.run_cli(fixture, "--agent", f"coderails:{role}")
                self.assert_bound(role, fixture.parent_tools(), "--agent")

    def test_agent_tool_dispatch_has_only_its_mcp_tools(self) -> None:
        """A dispatched child (Agent tool, subagent_type) gets the same tools array as the --agent session."""
        for role in ROLES:
            with self.subTest(role=role):
                fixture = RecordingFixture(role)
                self.addCleanup(fixture.close)
                self.run_cli(fixture)
                self.assert_bound(role, fixture.child_tools(), "dispatch")

    def test_wrong_role_tools_are_absent_from_the_session(self) -> None:
        """design-scout's tool list names no other role's server and no tests_run/cmd_run tool of any server."""
        fixture = RecordingFixture(None)
        self.addCleanup(fixture.close)
        self.run_cli(fixture, "--agent", "coderails:design-scout")
        tools = fixture.parent_tools()
        self.assertFalse([t for t in tools if "cap-source-auditor" in t], tools)
        self.assertFalse([t for t in tools if t.endswith(("__tests_run", "__cmd_run", "__pr_comment"))], tools)

    def test_negative_control_the_probe_detects_a_bash_bearing_agent(self) -> None:
        """Oracle check: an agent that does list Bash (the original frontmatter) shows Bash in the same request."""
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "plugin"
            (plugin / ".claude-plugin").mkdir(parents=True)
            (plugin / "agents").mkdir()
            (plugin / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "coderails", "version": "0"}))
            (plugin / "agents/bashy.md").write_text(
                "---\nname: bashy\ndescription: probe control\ntools: Read, Bash\n---\nbody\n"
            )
            fixture = RecordingFixture(None)
            self.addCleanup(fixture.close)
            with patch.object(sys.modules[__name__], "ROOT", plugin):
                self.run_cli(fixture, "--agent", "coderails:bashy")
            self.assertIn("Bash", fixture.parent_tools())


class LiveServerRefusalTest(unittest.TestCase):
    """The per-role servers the CLI launches refuse a tool or command outside the role (U1 behaviour, live stdio)."""

    def call(self, role: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run `capability_mcp.py --role <role>` over stdio and return the tools/call reply."""
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
        ]
        with tempfile.TemporaryDirectory() as loop:
            done = subprocess.run(
                [sys.executable, str(ROOT / "scripts/capability_mcp.py"), "--role", role],
                input="".join(json.dumps(m) + "\n" for m in lines),
                capture_output=True,
                text=True,
                cwd=ROOT,
                env={"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": loop, "CLAUDE_SESSION_ID": "s_probe"},
                check=False,
                timeout=60,
            )
        reply: dict[str, Any] = json.loads(done.stdout.splitlines()[1])
        return reply

    def test_design_scout_server_refuses_tests_run(self) -> None:
        """Wrong-role: a tool the role does not hold is a JSON-RPC error and nothing runs."""
        reply = self.call("design-scout", "tests_run", {"name": "scripts"})
        self.assertIn("error", reply)
        self.assertIn("not available", reply["error"]["message"])

    def test_source_auditor_cmd_run_refuses_unnamed_commands(self) -> None:
        """Arbitrary command: only profile-named commands run; `bash` and a raw argv are refused."""
        for name in ("bash", "sh -c id", "git-rev-count; id"):
            with self.subTest(name=name):
                reply = self.call("source-auditor", "cmd_run", {"name": name})
                self.assertTrue(reply["result"]["isError"], reply)
                self.assertFalse(json.loads(reply["result"]["content"][0]["text"])["ok"])


if __name__ == "__main__":
    unittest.main()
