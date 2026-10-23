"""Codex workers use a private home and require terminal structured output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

SCRIPTS = Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"
sys.path.insert(0, str(SCRIPTS))
import graph_driver_codex  # noqa: E402


class CodexBackendTests(unittest.TestCase):
    """Check the current OAuth CLI route and strict evidence parser."""

    def test_command_uses_codex_exec_and_current_login(self) -> None:
        """The worker uses the existing Codex login with explicit result controls."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            prompt = artifact / "prompt.txt"
            prompt.write_text("owned prompt\n")
            argv, environment, stdin_path = graph_driver_codex.command(prompt, artifact, cli="/fake/codex")
            self.assertEqual(argv[0], "/fake/codex")
            self.assertEqual(argv[1], "exec")
            self.assertIn("--json", argv)
            self.assertIn("--output-schema", argv)
            self.assertIn("--output-last-message", argv)
            self.assertIn("workspace-write", argv)
            self.assertIn("features.multi_agent=false", argv)
            self.assertEqual(argv[argv.index("--model") + 1], "gpt-6.1-sol")
            self.assertEqual(stdin_path, prompt)
            self.assertIsNone(environment)
            self.assertIn("--ignore-user-config", argv)

    def test_unguarded_role_rejects_checkout_codex_config(self) -> None:
        """A read-only worker cannot inherit a project MCP server outside its sandbox."""
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            (checkout / ".codex").mkdir()
            prompt = checkout / "prompt.txt"
            prompt.write_text("spec task\n")
            with self.assertRaisesRegex(ValueError, "project Codex config"):
                graph_driver_codex.command(prompt, checkout, cli="/fake/codex", role="spec-reviewer")

    def test_guarded_role_uses_its_capability_server_and_frozen_model(self) -> None:
        """A scout cannot inherit generic shell or write access."""
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            prompt = checkout / "prompt.txt"
            prompt.write_text("scout task\n")
            argv, environment, _ = graph_driver_codex.command(
                prompt, checkout, cli="/fake/codex", role="preflight-scout", model_role="frontier"
            )
            self.assertEqual(Path(argv[1]).name, "codex_role_session.py")
            self.assertEqual(argv[argv.index("--role") + 1], "preflight-scout")
            self.assertEqual(argv[argv.index("--schema") + 1], str(prompt.parent / "result.schema.json"))
            self.assertEqual(argv[argv.index("--model") + 1], "gpt-6-astra")
            self.assertIsNone(environment)

    def test_guarded_role_wrapper_launches_one_read_only_capability_session(self) -> None:
        """The guarded wrapper applies its profile before starting the model CLI."""
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            prompt = checkout / "prompt.txt"
            prompt.write_text("scout task\n")
            argv, _, _ = graph_driver_codex.command(prompt, checkout, role="preflight-scout", model_role="frontier")
            tool_dir = checkout / "bin"
            tool_dir.mkdir()
            capture = checkout / "args.json"
            fake = tool_dir / "codex"
            fake.write_text(
                "#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n"
                f"Path({str(capture)!r}).write_text(json.dumps(sys.argv[1:]))\n"
            )
            fake.chmod(0o755)
            run = subprocess.run(
                argv,
                cwd=checkout,
                env={**os.environ, "PATH": f"{tool_dir}:{os.environ['PATH']}"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            launched = json.loads(capture.read_text())
            self.assertIn("--ignore-user-config", launched)
            self.assertEqual(launched[launched.index("-s") + 1], "read-only")
            self.assertIn("features.shell_tool=false", launched)
            self.assertEqual(sum(value.startswith("mcp_servers.") for value in launched), 1)
            self.assertEqual(launched[launched.index("--model") + 1], "gpt-6-astra")

    def test_result_requires_successful_terminal_event_and_closed_json(self) -> None:
        """An exit code or plausible prose cannot stand in for completed structured output."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            output = artifact / "output.jsonl"
            final = artifact / "final.json"
            expected = {
                "outcome": "done",
                "evidence": "PR and test details",
                "final_report": {
                    "claims": [{"text": "Disposable result", "label": "verified", "source": "scratch checkout"}],
                    "did_not_verify": [],
                },
            }
            valid = (
                '{"type":"thread.started","thread_id":"T"}\n'
                + json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(expected)}}
                )
                + '\n{"type":"turn.completed"}\n'
            )
            output.write_text(valid)
            final.write_text(json.dumps(expected))
            self.assertEqual(graph_driver_codex.result(output, 0), expected)
            self.assertIn("skipped", cast(dict[str, Any], graph_driver_codex.SCHEMA)["properties"]["outcome"]["enum"])
            skipped = {"outcome": "skipped", "evidence": "wiki update is out of scope", "final_report": None}
            output.write_text(
                '{"type":"thread.started","thread_id":"T"}\n'
                + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(skipped)}})
                + '\n{"type":"turn.completed"}\n'
            )
            final.write_text(json.dumps(skipped))
            self.assertEqual(graph_driver_codex.result(output, 0), skipped)
            failed = {**expected, "outcome": "failed"}
            output.write_text(
                '{"type":"thread.started","thread_id":"T"}\n'
                + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(failed)}})
                + '\n{"type":"turn.completed"}\n'
            )
            final.write_text(json.dumps(failed))
            self.assertEqual(graph_driver_codex.result(output, 0), failed)
            output.write_text('{"type":"thread.started","thread_id":"T"}\n')
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            output.write_text('{"type":"turn.failed"}\n')
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            output.write_text(valid)
            final.write_text('{"outcome":"done","evidence":"x","extra":true}')
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            final.write_text(json.dumps({"outcome": "done", "evidence": "different"}))
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            final.write_text(json.dumps(expected))
            self.assertEqual(graph_driver_codex.result(output, 7)["outcome"], "failed")
            output.write_text(
                valid.replace(
                    '{"type":"turn.completed"}',
                    '{"type":"item.completed","item":{"type":"collab_tool_call"}}\n{"type":"turn.completed"}',
                )
            )
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
