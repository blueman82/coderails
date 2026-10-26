"""A stale review-pass line cannot pass as a legacy docs-only review."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.test_codex_review_passes import HOOK, HOOK_SHIM, Repo, artifact, entry, git_cmd, shim


class StaleDocsTests(Repo):
    """Use a docs-only diff, which needs no specialist review pass."""

    touched = "docs/a.md"

    def test_stale_line_is_malformed(self) -> None:
        """A present line for another head is refused even if the legacy marker would pass."""
        environment = {**os.environ, "PATH": f"{shim(self.tmp, HOOK_SHIM)}{os.pathsep}{os.environ['PATH']}"}
        environment |= {
            "FAKE_SHA": self.sha,
            "FAKE_BASE_SHA": git_cmd(self.dir, "rev-parse", "origin/main").strip(),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
            "FAKE_PASSES_SHA": "stale",
        }
        environment |= artifact(entry("review-pr"))
        payload = {
            "session_id": "s",
            "cwd": str(self.dir),
            "tool_name": "Bash",
            "tool_input": {"command": "gh pr merge 7"},
        }
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=environment
        )
        self.assertIn("review_passes_malformed", result.stdout)
