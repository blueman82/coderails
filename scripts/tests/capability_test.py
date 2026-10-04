"""Exercise scripts/capability.py end to end in throwaway git repos."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "capability.py"


class CapabilityCase(unittest.TestCase):
    """A scratch git repo with two commits and an isolated trace directory."""

    def setUp(self) -> None:
        """Build the repo, loop dir and environment."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.repo = self.dir / "repo"
        self.loop = self.dir / "loops"
        self.repo.mkdir()
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.dir),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            "CLAUDE_SESSION_ID": "s_cap",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.git("init", "-q")
        (self.repo / "a.txt").write_text("alpha\nbeta\n")
        self.git("add", ".")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one")
        (self.repo / "a.txt").write_text("alpha\nbeta\ngamma\n")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two")

    def git(self, *args: str) -> None:
        """Run git in the scratch repo."""
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True, env=self.env)

    def call(self, tool: str, args: object, **env: str) -> tuple[int, dict[str, Any]]:
        """Run capability.py and return (process exit code, parsed stdout JSON)."""
        done = subprocess.run(
            [sys.executable, str(SCRIPT), tool, "--json-args", json.dumps(args)],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env=self.env | env,
            check=False,
        )
        return done.returncode, json.loads(done.stdout)

    def rows(self) -> list[dict[str, Any]]:
        """Parse the trace rows written for the session."""
        path = self.loop / "s_cap" / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


class RepoInspectTests(CapabilityCase):
    """repo.inspect and diff.read return typed JSON and trace every call."""

    def test_read_returns_typed_envelope_and_traces(self) -> None:
        """Exit status, artifact sha, timestamp, evidence refs and one ok trace row."""
        code, out = self.call("repo.inspect", {"op": "read", "path": "a.txt"})
        self.assertEqual((code, out["ok"], out["exit_status"]), (0, True, 0))
        self.assertEqual(out["result"]["text"], "alpha\nbeta\ngamma\n")
        self.assertEqual(len(out["artifact_sha"]), 64)
        self.assertTrue(out["ts"].endswith("+00:00"))
        self.assertEqual(out["evidence"][0]["ref"], "a.txt")
        (row,) = self.rows()
        self.assertEqual((row["command"], row["outcome"], row["reason_code"]), ("capability", "ok", "repo.inspect"))

    def test_list_grep_status_log(self) -> None:
        """The other read ops work on the scratch repo."""
        self.assertIn("a.txt", self.call("repo.inspect", {"op": "list"})[1]["result"]["entries"])
        grep = self.call("repo.inspect", {"op": "grep", "pattern": "gamma"})[1]["result"]["matches"]
        self.assertEqual(grep, ["a.txt:3:gamma"])
        self.assertEqual(self.call("repo.inspect", {"op": "status"})[1]["result"]["lines"], [])
        self.assertEqual(len(self.call("repo.inspect", {"op": "log", "n": 5})[1]["result"]["lines"]), 2)

    def test_schema_and_path_refusals_are_typed_and_traced(self) -> None:
        """Unknown keys, wrong types, escapes and bad ops are refused with a stable code and a trace row."""
        (self.dir / "secret.txt").write_text("s")
        (self.repo / "link").symlink_to(self.dir / "secret.txt")
        bad: list[tuple[str, object]] = [
            ("repo.inspect", {"op": "read", "path": "a.txt", "extra": 1}),
            ("repo.inspect", {"op": "read", "path": 5}),
            ("repo.inspect", {"op": "read", "path": "../secret.txt"}),
            ("repo.inspect", {"op": "read", "path": str(self.dir / "secret.txt")}),
            ("repo.inspect", {"op": "read", "path": "link"}),
            ("repo.inspect", {"op": "rm", "path": "a.txt"}),
            ("repo.inspect", {"op": "log", "n": True}),
            ("repo.inspect", {"op": "log", "n": 9999}),
            ("repo.inspect", ["not", "an", "object"]),
            ("diff.read", {"base": "--output=x"}),
            ("diff.read", {"base": "nope-no-such-ref"}),
            ("diff.read", {"base": "HEAD", "paths": ["../x"]}),
        ]
        for tool, args in bad:
            with self.subTest(tool=tool, args=args):
                code, out = self.call(tool, args)
                self.assertEqual((code, out["ok"]), (2, False))
                self.assertTrue(out["refusal"].startswith("capability_"), out)
        self.assertEqual([r["outcome"] for r in self.rows()], ["refused"] * len(bad))

    def test_unknown_tool_and_bad_argv_refused(self) -> None:
        """A tool that is not in the table, or a missing --json-args, is refused."""
        self.assertEqual(self.call("repo.nuke", {})[1]["refusal"], "capability_unknown_tool")
        done = subprocess.run(
            [sys.executable, str(SCRIPT), "repo.inspect"], cwd=self.repo, capture_output=True, text=True, env=self.env
        )
        self.assertEqual(json.loads(done.stdout)["refusal"], "capability_bad_argv")

    def test_shell_metacharacters_are_inert(self) -> None:
        """A pattern full of shell syntax is one literal argv element and creates nothing."""
        pattern = "$(touch pwned); `touch pwned2` | touch pwned3 > pwned4"
        code, out = self.call("repo.inspect", {"op": "grep", "pattern": pattern})
        self.assertEqual((code, out["result"]["matches"]), (0, []))
        self.assertEqual(sorted(p.name for p in self.repo.iterdir() if p.name.startswith("pwned")), [])
        self.assertEqual(self.call("repo.inspect", {"op": "grep", "pattern": "-n"})[0], 0)

    def test_diff_read(self) -> None:
        """diff.read returns the unified diff, resolved shas as evidence, and honours max_bytes."""
        code, out = self.call("diff.read", {"base": "HEAD~1", "head": "HEAD"})
        self.assertEqual(code, 0)
        self.assertIn("+gamma", out["result"]["diff"])
        self.assertEqual({e["kind"] for e in out["evidence"]}, {"commit"})
        self.assertEqual(len(out["evidence"][0]["sha"]), 40)
        small = self.call("diff.read", {"base": "HEAD~1", "max_bytes": 10})[1]["result"]
        self.assertTrue(small["truncated"])
        self.assertEqual(len(small["diff"]), 10)

    def test_trace_failure_and_torn_row_fail_open(self) -> None:
        """An unwritable trace dir or a torn existing trace row never changes the capability result."""
        blocker = self.dir / "file"
        blocker.write_text("x")
        code, out = self.call("repo.inspect", {"op": "list"}, CLAUDE_AGENTIC_LOOP_DIR=str(blocker / "sub"))
        self.assertEqual((code, out["ok"]), (0, True))
        trace = self.loop / "s_cap" / "trace.jsonl"
        trace.parent.mkdir(parents=True)
        trace.write_text('{"schema_version": 1, "comm')  # torn: no newline, truncated JSON
        code, out = self.call("repo.inspect", {"op": "list"})
        self.assertEqual((code, out["ok"]), (0, True))
        self.assertIn('"outcome": "ok"', trace.read_text())

    def test_no_session_still_writes_unattributed_row(self) -> None:
        """Without a session id, calls and refusals are traced under the `unattributed` bucket, not dropped."""
        env = dict(self.env)
        del env["CLAUDE_SESSION_ID"]
        self.env = env
        code, out = self.call("repo.inspect", {"op": "list"})
        self.assertEqual((code, out["traced"]), (0, True))
        refused = self.call("bogus", {})[1]
        self.assertTrue(refused["traced"])
        rows = [json.loads(x) for x in (self.loop / "unattributed" / "trace.jsonl").read_text().splitlines()]
        self.assertEqual([r["session_id"] for r in rows], ["unattributed"] * 2)
        self.assertEqual(rows[1]["reason_code"], "capability_unknown_tool")

    def test_traced_true_with_session(self) -> None:
        """With a session id the envelope says the row was written."""
        self.assertTrue(self.call("repo.inspect", {"op": "list"})[1]["traced"])


if __name__ == "__main__":
    unittest.main()
