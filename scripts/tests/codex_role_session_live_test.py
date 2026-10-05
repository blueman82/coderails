"""Observe the real Codex CLI against a loopback Responses fixture: does the role session really have no shell?

The fixture answers the first request with an `exec_command` function_call. With the shell tool on the command
runs; with
`features.shell_tool=false` the tool is absent from the request's `tools` array and the call comes back "unsupported".
Scope of the observation: the argv the launcher builds, run by `codex exec`; role TOML files themselves are asserted by
the validator, not observed here. No network beyond loopback, no billing (placeholder key, fixture provider).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import codex_role_session as crs  # noqa: E402

SHELL_TOOLS = {"exec_command", "write_stdin"}


class ResponsesFixture:
    """Loopback /v1/responses server: one exec_command call, then a final message once an output arrives."""

    def __init__(self) -> None:
        """Start serving on an ephemeral loopback port."""
        self.bodies: list[dict[str, Any]] = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            """Serve SSE responses; never log bodies."""

            def log_message(self, format: str, *args: object) -> None:
                """Silence request logging."""

            def do_POST(self) -> None:
                """Record the body and stream the scripted turn."""
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                fixture.bodies.append(body)
                item: dict[str, Any]
                if "function_call_output" in json.dumps(body):
                    item = {"type": "message", "id": "m1", "role": "assistant"}
                    item["content"] = [{"type": "output_text", "text": "DONE"}]
                else:
                    args = json.dumps({"cmd": "echo SHELL_RAN"})
                    item = {"type": "function_call", "id": "fc1", "call_id": "call_1", "name": "exec_command"}
                    item["arguments"] = args
                usage = {"input_tokens": 1, "input_tokens_details": None, "output_tokens": 1}
                usage |= {"output_tokens_details": None, "total_tokens": 2}
                events = [
                    ("response.created", {"type": "response.created", "response": {"id": "r"}}),
                    ("response.output_item.done", {"type": "response.output_item.done", "item": item}),
                    ("response.completed", {"type": "response.completed", "response": {"id": "r", "usage": usage}}),
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for name, data in events:
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        """Stop serving."""
        self.server.shutdown()
        self.server.server_close()

    def tool_names(self) -> list[str]:
        """Tool names of the first request; namespaced (MCP) tools are listed as `namespace.name`."""

        def walk(tools: list[dict[str, Any]], prefix: str) -> list[str]:
            names: list[str] = []
            for tool in tools:
                name = prefix + str(tool.get("name") or tool.get("type"))
                names += [name] + walk(list(tool.get("tools", [])), name + ".")
            return names

        return walk(self.bodies[0].get("tools", []), "")

    def outputs(self) -> str:
        """The function_call_output text the CLI sent back to the model."""
        text = json.dumps(self.bodies[-1])
        return text[text.find("function_call_output") :][:300]


@unittest.skipUnless(shutil.which("codex"), "real Codex CLI is required for the role-session observation")
class CodexRoleSessionLiveTest(unittest.TestCase):
    """The launcher's argv, executed by the real CLI."""

    def run_session(self, argv: list[str]) -> ResponsesFixture:
        """Run `argv` (the launcher's command, minus the stdin marker) against a fresh fixture."""
        fixture = ResponsesFixture()
        self.addCleanup(fixture.close)
        tmp = tempfile.mkdtemp(prefix="coderails-codex-live-")
        self.addCleanup(shutil.rmtree, tmp, True)  # codex may still be writing plugin caches as it exits
        work = Path(tmp) / "work"
        work.mkdir()
        provider = f'{{name="fx", base_url="http://127.0.0.1:{fixture.server.server_port}/v1", '
        provider += 'wire_api="responses", env_key="FX_KEY"}'
        command = argv[:-1] + ["-C", str(work), "--skip-git-repo-check"]
        command += ["-c", f"model_providers.fx={provider}", "-c", 'model_provider="fx"', "-c", 'model="gpt-5"']
        env = {"PATH": os.environ["PATH"], "HOME": tmp, "CODEX_HOME": f"{tmp}/.codex", "FX_KEY": "placeholder"}
        os.makedirs(env["CODEX_HOME"])
        done = subprocess.run(
            command, input="run echo SHELL_RAN", env=env, capture_output=True, text=True, timeout=90, check=False
        )
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        self.assertTrue(fixture.bodies, "the CLI never reached the fixture")
        return fixture

    def test_role_session_has_no_shell_tool_and_the_call_is_unsupported(self) -> None:
        """source-auditor's launcher argv: no exec_command/write_stdin offered, the scripted call is refused."""
        fixture = self.run_session(crs.build_argv("source-auditor", REPO))
        names = fixture.tool_names()
        self.assertEqual(SHELL_TOOLS & set(names), set(), names)
        self.assertIn("unsupported call: exec_command", fixture.outputs())
        self.assertNotIn("SHELL_RAN", fixture.outputs())
        self.assertTrue(any(n.endswith("cmd_run") for n in names), names)
        self.assertTrue(any(n.endswith("tests_run") for n in names), names)

    def test_negative_control_without_the_switch_the_shell_runs(self) -> None:
        """The same argv minus features.shell_tool=false offers the shell and the command executes."""
        argv = crs.build_argv("source-auditor", REPO)
        at = argv.index("features.shell_tool=false")
        fixture = self.run_session(argv[: at - 1] + argv[at + 1 :])
        self.assertEqual(SHELL_TOOLS & set(fixture.tool_names()), SHELL_TOOLS)
        self.assertIn("SHELL_RAN", fixture.outputs())

    def test_only_the_requested_roles_server_is_registered(self) -> None:
        """design-scout's session lists design-scout's MCP tools and none of source-auditor's tests_run/cmd_run."""
        fixture = self.run_session(crs.build_argv("design-scout", REPO))
        mcp = [n for n in fixture.tool_names() if "cap" in n and ("inspect" in n or "diff" in n or "run" in n)]
        self.assertTrue(any("repo_inspect" in n for n in mcp), fixture.tool_names())
        self.assertFalse([n for n in mcp if "tests_run" in n or "cmd_run" in n], mcp)


if __name__ == "__main__":
    unittest.main()
