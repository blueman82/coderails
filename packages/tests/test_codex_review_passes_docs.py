"""Docs-only diff acceptance through the native Codex review gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys

from packages.tests.test_codex_review_passes import HOOK, HOOK_SHIM, Repo, artifact, entry, git_cmd, shim


class DocsOnlyTests(Repo):
    """A docs-only PR needs only review-pr."""

    touched = "docs/a.md"
    eval_level = 0

    def test_docs_only_needs_review_pr_only(self) -> None:
        """A valid review pair with only review-pr permits a docs-only diff."""
        environment = {**os.environ, "PATH": f"{shim(self.tmp, HOOK_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        environment |= {
            "FAKE_SHA": self.sha,
            "FAKE_BASE_SHA": git_cmd(self.dir, "rev-parse", "origin/main").strip(),
            "FAKE_EVAL_FILE": str(self.eval_file),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
            **artifact(entry("review-pr")),
        }
        command = {"command": "gh pr merge 7"}
        payload = {"session_id": "s", "cwd": str(self.dir), "tool_name": "Bash", "tool_input": command}
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=environment
        )
        self.assertEqual((result.returncode, result.stdout.strip()), (0, ""))


if __name__ == "__main__":
    import unittest

    unittest.main()
