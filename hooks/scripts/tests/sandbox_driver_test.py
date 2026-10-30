"""The Claude driver reaches the pinned sandbox without polluting JSONL."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class SandboxDriverTests(unittest.TestCase):
    """Run the real launcher with disposable npx and gh executables."""

    def test_driver_mode_uses_pinned_srt_and_json_schema(self) -> None:
        """The sandbox path gets structured output and no prose header."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            prompt = base / "prompt.txt"
            prompt.write_text("owned worker prompt\n")
            bindir = base / "bin"
            bindir.mkdir()
            capture = base / "argv.json"
            npx = bindir / "npx"
            npx.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\nfrom pathlib import Path\n"
                "Path(os.environ['DRIVER_ARGV_CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
                "print('sandbox-diagnostic-marker', file=sys.stderr)\n"
                "print(json.dumps({'type':'system','subtype':'init','session_id':'fake'}))\n"
                "print(json.dumps({'type':'result','subtype':'success','is_error':False,"
                "'structured_output':{'outcome':'done','evidence':'fake'}}))\n"
            )
            npx.chmod(0o755)
            gh = bindir / "gh"
            gh.write_text("#!/bin/sh\nprintf 'fake-token\\n'\n")
            gh.chmod(0o755)
            home = base / "home"
            home.mkdir()
            foreign = {"mcpServers": {"foreign": {"command": "/never/run/foreign"}}}
            (checkout / ".mcp.json").write_text(json.dumps(foreign))
            (home / ".claude.json").write_text(json.dumps(foreign))
            environment = {
                **os.environ,
                "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
                "DRIVER_ARGV_CAPTURE": str(capture),
                "TMPDIR": str(base),
                "CLAUDE_CODE_SESSION_ID": "",
                "HOME": str(home),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            }
            launcher = ROOT / "scripts/sandbox/spawn_sandboxed_worker.py"
            run = subprocess.run(
                [sys.executable, str(launcher), "--driver", str(checkout), str(prompt), "sonnet"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertNotIn("sandbox-diagnostic-marker", run.stdout)
            self.assertIn("worker.stderr.log", run.stderr)
            logs = list(base.glob("sandbox-worker.*/worker.stderr.log"))
            self.assertEqual(len(logs), 1)
            self.assertIn("sandbox-diagnostic-marker", logs[0].read_text())
            self.assertEqual(json.loads(run.stdout.splitlines()[0])["type"], "system")
            argv = json.loads(capture.read_text())
            self.assertIn("@anthropic-ai/sandbox-runtime@0.0.65", argv)
            self.assertIn("--json-schema", argv)
            self.assertIn("stream-json", argv)
            self.assertIn("Agent", argv[argv.index("--disallowedTools") + 1])
            self.assertIn("Bash", argv[argv.index("--allowedTools") + 1])
            self.assertNotIn("--tools", argv)
            self.assertNotIn("--strict-mcp-config", argv)
            self.assertNotIn("owned worker prompt", " ".join(argv))
            guarded = subprocess.run(
                [sys.executable, str(launcher), "--driver", str(checkout), str(prompt), "sonnet", "preflight-scout"],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(guarded.returncode, 0, guarded.stderr)
            scout_argv = json.loads(capture.read_text())
            self.assert_guarded(scout_argv)

    def assert_guarded(self, scout_argv: list[str]) -> None:
        """The actual public launch argv closes built-ins, agent defaults and foreign MCP."""
        self.assertNotIn("Bash", scout_argv[scout_argv.index("--allowedTools") + 1])
        self.assertIn("Bash", scout_argv[scout_argv.index("--disallowedTools") + 1])
        self.assertIn("--tools", scout_argv)
        self.assertEqual(scout_argv[scout_argv.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", scout_argv)
        self.assertIn("--agent", scout_argv)
        definitions = json.loads(scout_argv[scout_argv.index("--agents") + 1])
        selected = definitions[scout_argv[scout_argv.index("--agent") + 1]]
        self.assertEqual(
            set(selected["tools"]),
            {
                "mcp__plugin_coderails_cap-preflight-scout__repo_inspect",
                "mcp__plugin_coderails_cap-preflight-scout__diff_read",
            },
        )
        config = json.loads(scout_argv[scout_argv.index("--mcp-config") + 1])
        servers = config["mcpServers"]
        self.assertEqual(set(servers), {"plugin_coderails_cap-preflight-scout"})
        server = servers["plugin_coderails_cap-preflight-scout"]
        self.assertEqual(server["command"], sys.executable)
        self.assertEqual(server["args"], [str(ROOT / "scripts/capability_mcp.py"), "--role", "preflight-scout"])


if __name__ == "__main__":
    unittest.main()
