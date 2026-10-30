"""A native session must bind both providers' push publication."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from packages.tests.graph_manifest_fixture import graph_progress  # noqa: E402
from scripts.tests.manifest_policy_test import RepoCase, git_cmd  # noqa: E402
from scripts.tests.publication_gate_test import install_gh_shim  # noqa: E402


class PushSessionTests(RepoCase):
    """Use a real graph, local bare remote, and fake gh for both plugin installs."""

    def check_provider(self, provider: str) -> None:
        """No session refuses; the same repository and unit publish with a session."""
        bare = self.dir.parent / "bare.git"
        git_cmd(self.dir.parent, "init", "-q", "--bare", str(bare))
        git_cmd(self.dir, "remote", "add", "origin", "https://github.com/o/r.git")
        git_cmd(self.dir, "config", "remote.origin.pushurl", str(bare))
        git_cmd(self.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        (self.dir / "README.md").write_text("changed\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        progress = graph_progress(self.dir, self.loop, ["README.md"], provider=provider)
        command = ROOT / ("packages/codex/scripts/push.py" if provider == "codex" else "scripts/push.py")
        environment = os.environ | {
            "PATH": f"{install_gh_shim(self.dir.parent)}{os.pathsep}{os.environ['PATH']}",
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.loop),
            "CODERAILS_PUBLICATION_SESSION_ID": "",
            "CLAUDE_CODE_SESSION_ID": "",
            "CODEX_SESSION_ID": "",
            "CODEX_THREAD_ID": "",
        }
        flags = ["--unit", "2", "--progress", str(progress)]
        for arguments in ([], flags):
            with self.subTest(provider=provider, arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(command), *arguments],
                    cwd=self.dir,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("publication:session_missing", result.stderr)
                self.assertEqual(git_cmd(bare, "for-each-ref", "refs/heads").strip(), "")
        environment["CODERAILS_PUBLICATION_SESSION_ID"] = "s"
        result = subprocess.run(
            [sys.executable, str(command), *flags], cwd=self.dir, env=environment, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("refs/heads/feature/x", git_cmd(bare, "for-each-ref", "refs/heads"))

    def test_claude_push_requires_session(self) -> None:
        """The Claude push uses the publication session check."""
        self.check_provider("claude")

    def test_codex_push_requires_session(self) -> None:
        """The Codex push uses the same check in its package mirror."""
        self.check_provider("codex")

    def test_explicit_unit_refuses_missing_graph_owner_for_both_providers(self) -> None:
        """A broken graph owner cannot turn an explicit unit push into a standalone push."""
        bare = self.dir.parent / "bare.git"
        git_cmd(self.dir.parent, "init", "-q", "--bare", str(bare))
        git_cmd(self.dir, "remote", "add", "origin", "https://github.com/o/r.git")
        git_cmd(self.dir, "config", "remote.origin.pushurl", str(bare))
        git_cmd(self.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        (self.dir / "README.md").write_text("changed\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        progress = graph_progress(self.dir, self.loop, ["README.md"])
        valid = json.loads(progress.read_text())
        environment = os.environ | {
            "PATH": f"{install_gh_shim(self.dir.parent)}{os.pathsep}{os.environ['PATH']}",
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.dir.parent / "inactive-graphs"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.dir.parent / "inactive-graphs"),
            "CODERAILS_PUBLICATION_SESSION_ID": "s",
        }
        for field in ("session_id", "loop_id"):
            progress.write_text(json.dumps({**valid, field: ""}))
            for provider in ("claude", "codex"):
                with self.subTest(field=field, provider=provider):
                    command = ROOT / ("packages/codex/scripts/push.py" if provider == "codex" else "scripts/push.py")
                    result = subprocess.run(
                        [sys.executable, str(command), "--unit", "2", "--progress", str(progress)],
                        cwd=self.dir,
                        env=environment,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("publication:graph_owner_missing", result.stderr)
                    self.assertEqual(git_cmd(bare, "for-each-ref", "refs/heads").strip(), "")
                    trace = self.dir.parent / "inactive-graphs" / "s" / "trace.jsonl"
                    row = json.loads(trace.read_text().splitlines()[-1])
                    self.assertEqual(
                        (row["command"], row["outcome"], row["reason_code"]),
                        ("publication", "refused", "graph_owner_missing"),
                    )


if __name__ == "__main__":
    unittest.main()
