"""Exercise native Claude dispatch and hooks with an offline model-side fixture.

The installed CLI executes real Agent calls and owns all native transcript writes.
These checks validate CLI integration, not live Claude model reasoning or billing.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_dispatch as dispatch
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.graph_evidence import notifications, transcript
from hooks.scripts.lib.graph_executor import load
from hooks.scripts.tests.lib import claude_transcript_fixture as fixture
from hooks.scripts.tests.lib.native_api_fixture import NativeAPIFixture

ROOT = Path(__file__).resolve().parents[3]


@unittest.skipUnless(shutil.which("claude"), "real Claude CLI is required for native integration acceptance")
class ClaudeCLIAcceptanceTest(unittest.TestCase):
    """Keep fixtures on the API side of the actual CLI's native execution boundary."""

    def setUp(self) -> None:
        """Allocate private session state and credentials that only the local fixture accepts."""
        temporary = tempfile.TemporaryDirectory(prefix="coderails-claude-native-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.cwd = self.home / "work"
        self.cwd.mkdir()
        self.session = str(uuid.uuid4())
        environment = patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "CLAUDE_CONFIG_DIR": str(self.home / ".claude"),
                "CLAUDE_PROJECTS_DIR": str(self.home / ".claude/projects"),
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.home / "loops"),
                "ANTHROPIC_API_KEY": "local-fixture-not-a-credential",
                "ANTHROPIC_AUTH_TOKEN": "local-fixture-not-a-credential",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        self.path = resolve_path(str(self.cwd), self.session)
        graph = fixture.state(2)
        graph["session_id"] = self.session
        graph["work_units"] = {"unit": {"status": "pending"}}
        fixture.write_json(self.path, graph)
        suite = fixture.frozen_evals()
        suite["session_id"] = self.session
        fixture.write_json(self.path.with_name("evals.json"), suite)
        self.bad_envelope = False
        self.preparing = True

    def dispatches(self) -> list[dict[str, Any]]:
        """Ask the actual CLI for two workers using its native general-purpose role."""
        if self.preparing:
            return [{"type": "text", "text": "NATIVE_SESSION_INITIALIZED"}]
        opened = dispatch.begin_wave(self.path)
        graph = load(self.path)
        blocks: list[dict[str, Any]] = []
        for index, node in enumerate(opened["nodes"]):
            ownership = dispatch.ownership(graph, node)
            if self.bad_envelope:
                ownership["wave_id"] = "wave-foreign"
            prompt = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(ownership) + "\n"
            prompt += (ROOT / "agents/loop-worker.md").read_text()
            prompt += "\nTask: return NATIVE_CHILD_COMPLETED. No files, commits, network calls or further agents."
            blocks.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_graph_fixture_{index}",
                    "name": "Agent",
                    "input": {
                        "subagent_type": "general-purpose",
                        "description": f"Native graph fixture {index}",
                        "prompt": prompt,
                    },
                }
            )
        return blocks

    def run_cli(self) -> tuple[subprocess.CompletedProcess[str], NativeAPIFixture]:
        """Run the real CLI with the current production PreToolUse guard enabled."""
        server = NativeAPIFixture(self.dispatches)
        self.addCleanup(server.close)
        environment = dict(os.environ)
        environment["ANTHROPIC_BASE_URL"] = server.url
        for key in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
            environment.pop(key, None)
        command = shlex.join([sys.executable, str(ROOT / "hooks/scripts/loop_dispatch_guard.py")])
        settings = {"hooks": {"PreToolUse": [{"matcher": "Agent", "hooks": [{"type": "command", "command": command}]}]}}
        args = [
            "claude",
            "--model",
            "sonnet",
            "-p",
            "Execute the native graph integration fixture.",
            "--output-format",
            "stream-json",
            "--verbose",
            "--session-id",
            self.session,
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--settings",
            json.dumps(settings),
            "--allowedTools",
            "Agent",
            "--tools",
            "Agent",
        ]
        warmup = subprocess.run(args, cwd=self.cwd, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(warmup.returncode, 0, warmup.stderr + warmup.stdout[-2000:])
        self.preparing = False
        args[args.index("--session-id")] = "--resume"
        result = subprocess.run(args, cwd=self.cwd, env=environment, capture_output=True, text=True, timeout=30)
        self.assertFalse(server.errors, server.errors)
        self.assertLessEqual(server.requests, 16)
        return result, server

    def test_real_native_hook_refuses_foreign_wave(self) -> None:
        """The real CLI obeys a production hook denial and creates no child completion."""
        self.bad_envelope = True
        result, _ = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout[-2000:])
        self.assertIn("loop-dispatch-guard", result.stdout)
        native = transcript(self.session)
        self.assertFalse(notifications(native, self.session))
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            dispatch.record_wave(self.path, fixture.report(load(self.path)))
        self.assertEqual(self.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
