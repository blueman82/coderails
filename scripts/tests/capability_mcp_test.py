"""Spawn the real per-role MCP server and speak JSON-RPC to it: tool set, wrong role, arbitrary command, drift."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capability_profiles_validate import validate  # noqa: E402
from scripts.tests.capability_extra_test import git, make_tree  # noqa: E402

READ_ONLY = ["diff_read", "repo_inspect"]
EXPECTED = {
    "deploy-safety-reviewer": READ_ONLY,
    "design-scout": READ_ONLY,
    "disposition-scout": READ_ONLY,
    "preflight-scout": READ_ONLY,
    "source-auditor": ["cmd_run", "diff_read", "repo_inspect", "tests_run"],
}


class Server:
    """One `capability_mcp.py --role` subprocess driven over newline-delimited JSON-RPC."""

    def __init__(self, script: Path, role: str, cwd: Path, loop: Path) -> None:
        """Start the server and complete the initialize handshake."""
        env = {"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": str(loop), "CLAUDE_CODE_SESSION_ID": "sess"}
        self.proc = subprocess.Popen(
            [sys.executable, str(script), "--role", role],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def send(self, message: dict[str, Any]) -> None:
        """Write one JSON line."""
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a request and return the matching response."""
        self.n += 1
        self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        assert self.proc.stdout
        reply: dict[str, Any] = json.loads(self.proc.stdout.readline())
        assert reply["id"] == self.n
        return reply

    def tools(self) -> list[str]:
        """Sorted tool names the server lists."""
        return sorted(t["name"] for t in self.rpc("tools/list")["result"]["tools"])

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """tools/call; the response (result or error)."""
        return self.rpc("tools/call", {"name": name, "arguments": arguments})

    def envelope(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """The typed envelope inside a tools/call result."""
        reply = self.call(name, arguments)
        body: dict[str, Any] = json.loads(reply["result"]["content"][0]["text"])
        return body

    def close(self) -> None:
        """Close stdin and reap."""
        assert self.proc.stdin and self.proc.stdout and self.proc.stderr
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


class McpCase(unittest.TestCase):
    """Real subprocesses against a scratch repo with a pristine tree copy; rows land in a scratch loop dir."""

    def setUp(self) -> None:
        """Build the scratch repo, tree copy and loop dir."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.repo = self.base / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "a.txt").write_text("one\ntwo\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "init")
        self.loop = self.base / "loop"
        self.tree = make_tree(self.base)
        self.sentinel = "sentinel.txt"

    def start(self, role: str, tree: Path | None = None) -> Server:
        """Start a server for role (default: the pristine tree) and register cleanup."""
        server = Server((tree or self.tree) / "scripts/capability_mcp.py", role, self.repo, self.loop)
        self.addCleanup(server.close)
        return server

    def with_sentinel(self, name: str) -> Path:
        """A tree whose profile declares a `sentinel` named command that touches a repo file."""
        tree = make_tree(self.base, name)
        path = tree / "capabilities/profiles.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["named_commands"]["sentinel"] = {"argv": ["touch", "{path}"], "params": {"path": "repo_path"}}
        path.write_text(json.dumps(data), encoding="utf-8")
        return tree

    def rows(self) -> list[dict[str, Any]]:
        """All trace rows written under the scratch loop dir."""
        found = list(self.loop.glob("*/trace.jsonl"))
        return [json.loads(line) for f in found for line in f.read_text(encoding="utf-8").splitlines()]

    def codes(self) -> list[str]:
        """Reason codes of traced capability rows."""
        return [r["reason_code"] for r in self.rows() if r["command"] == "capability"]

    def test_tools_list_matches_profile_for_each_role(self) -> None:
        """(a) exactly the profile-derived, MCP-safe tool names; no role property in any schema."""
        for role, expected in EXPECTED.items():
            with self.subTest(role=role):
                server = self.start(role)
                self.assertEqual(server.tools(), expected)
                for tool in server.rpc("tools/list")["result"]["tools"]:
                    self.assertNotIn("role", tool["inputSchema"].get("properties", {}))
        self.assertEqual(self.start("design-scout").rpc("ping")["result"], {})

    def test_wrong_role_call_errors_traces_and_runs_nothing(self) -> None:
        """(b) design-scout asked for tests_run/cmd_run: JSON-RPC error, wrong_role row, sentinel never created."""
        tree = self.with_sentinel("sent")
        server = self.start("design-scout", tree)
        for name, arguments in (
            ("cmd_run", {"name": "sentinel", "args": {"path": self.sentinel}}),
            ("tests_run", {"name": "scripts"}),
            ("nope", {}),
        ):
            reply = server.call(name, arguments)
            self.assertIn("error", reply, name)
        self.assertEqual(self.codes().count("capability_wrong_role"), 3)
        self.assertFalse((self.repo / self.sentinel).exists())

    def test_negative_control_without_allowlist_check_sentinel_runs(self) -> None:
        """Control: dispatching from the full table (no allowlist) lets design-scout run the sentinel."""
        tree = self.with_sentinel("sent2")
        doctor = {"scripts/capability_mcp.py": ("allowed.get(name)", "ALL_TOOLS.get(name)")}
        doctored = make_tree(self.base, "doc", doctor)
        profiles = "capabilities/profiles.json"
        (doctored / profiles).write_text((tree / profiles).read_text(encoding="utf-8"), encoding="utf-8")
        server = self.start("design-scout", doctored)
        server.call("cmd_run", {"name": "sentinel", "args": {"path": self.sentinel}})
        self.assertTrue((self.repo / self.sentinel).exists())

    def test_arbitrary_commands_refused_and_not_run(self) -> None:
        """(c) unknown name, extra key, bad path, bad ref: typed refusals with isError, nothing executed."""
        tree = self.with_sentinel("sent3")
        server = self.start("source-auditor", tree)
        good = server.envelope("cmd_run", {"name": "file-lines", "args": {"path": "a.txt"}})
        self.assertTrue(good["ok"], good)
        self.assertIn("2", good["result"]["stdout_tail"])
        bad: list[tuple[dict[str, Any], str]] = [
            ({"name": "echo", "args": {}}, "capability_args_invalid"),
            ({"name": "sentinel", "args": {"path": self.sentinel, "argv": "x"}}, "capability_args_invalid"),
            ({"name": "sentinel", "args": {"path": "../" + self.sentinel}}, "capability_path_denied"),
            ({"name": "sentinel", "args": {"path": str(self.base / self.sentinel)}}, "capability_path_denied"),
            ({"name": "git-rev-count", "args": {"ref": "HEAD && touch " + self.sentinel}}, "capability_bad_ref"),
            ({"name": "git-rev-count", "args": {"ref": "`touch " + self.sentinel + "`"}}, "capability_bad_ref"),
        ]
        for arguments, code in bad:
            with self.subTest(arguments=arguments):
                reply = server.call("cmd_run", arguments)
                self.assertTrue(reply["result"]["isError"])
                self.assertEqual(json.loads(reply["result"]["content"][0]["text"])["refusal"], code)
        self.assertFalse((self.repo / self.sentinel).exists())
        self.assertFalse((self.base / self.sentinel).exists())

    def test_role_argument_rejected(self) -> None:
        """(d) a smuggled `role` is an unknown key on every tool."""
        server = self.start("source-auditor")
        for name, arguments in (
            ("repo_inspect", {"op": "list", "role": "design-scout"}),
            ("cmd_run", {"name": "file-lines", "args": {"path": "a.txt"}, "role": "x"}),
            ("diff_read", {"base": "HEAD", "role": "x"}),
        ):
            env = json.loads(server.call(name, arguments)["result"]["content"][0]["text"])
            self.assertEqual(env["refusal"], "capability_args_invalid", name)

    def test_profile_is_source_of_truth_and_startup_refusals(self) -> None:
        """(e) editing a profile copy changes tools/list; the validator flags it; bad roles/flags exit 2."""
        path = self.tree / "capabilities/profiles.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["agents"]["design-scout"].append("tests.run")
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.start("design-scout").tools(), ["diff_read", "repo_inspect", "tests_run"])
        self.assertTrue(validate(ROOT, data), "validator must flag the profile/agent disagreement")
        script = str(self.tree / "scripts/capability_mcp.py")
        env = {"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop), "CLAUDE_CODE_SESSION_ID": "sess"}
        refused: list[list[str]] = [["--role", "ghost"], ["--role", "spec-reviewer"], ["--role", "loop-worker"], []]
        for argv in (*refused, ["--role", "design-scout", "--bad"]):
            with self.subTest(argv=argv):
                done = subprocess.run(
                    [sys.executable, script, *argv],
                    capture_output=True,
                    text=True,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
                self.assertEqual(done.returncode, 2)
                self.assertTrue(done.stderr.strip())
        self.assertGreaterEqual(self.codes().count("capability_mcp_refused"), 5)

    def test_negative_control_hard_coded_tools_ignore_profile_edit(self) -> None:
        """Control: a server with a hard-coded tool set fails the drift assertion above."""
        doctor = {"scripts/capability_mcp.py": ('profile["agents"][role]', '["repo.inspect", "diff.read"]')}
        doctored = make_tree(self.base, "hard", doctor)
        path = doctored / "capabilities/profiles.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["agents"]["design-scout"].append("tests.run")
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertNotIn("tests_run", self.start("design-scout", doctored).tools())

    def test_worktree_outside_list_refused(self) -> None:
        """(f) a worktree argument that is not in `git worktree list` is refused through MCP."""
        server = self.start("design-scout")
        env = server.envelope("repo_inspect", {"op": "list", "worktree": str(self.base)})
        self.assertEqual(env["refusal"], "capability_path_denied")

    def test_lone_surrogate_path_is_refused_and_server_survives(self) -> None:
        """(h) a lone-surrogate path yields an isError envelope, not a dead server."""
        server = self.start("design-scout")
        env = server.envelope("repo_inspect", {"op": "sha256", "path": "\ud800x"})
        self.assertEqual(env["refusal"], "capability_args_invalid")
        self.assertIn("repo_inspect", server.tools())

    def test_python39_syntax_and_import(self) -> None:
        """(g) the three new modules parse as 3.9 and import under this interpreter."""
        for rel in (
            "scripts/capability_mcp.py",
            "scripts/lib/capability_extra.py",
            "scripts/lib/capability_counters.py",
        ):
            ast.parse((ROOT / rel).read_text(encoding="utf-8"), feature_version=(3, 9))
        code = "import scripts.capability_mcp, scripts.lib.capability_extra, scripts.lib.capability_counters"
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_calls_are_traced_with_via_mcp(self) -> None:
        """An allowed call writes an ok row whose inputs hash tool, role and via."""
        self.start("design-scout").envelope("repo_inspect", {"op": "list"})
        row = [r for r in self.rows() if r["command"] == "capability" and r["outcome"] == "ok"][0]
        self.assertEqual(set(row["inputs"]), {"tool", "role", "via"})


if __name__ == "__main__":
    unittest.main()
