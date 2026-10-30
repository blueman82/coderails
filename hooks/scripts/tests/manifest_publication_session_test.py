#!/usr/bin/env python3
"""Bind Claude publication checks to the hook payload session."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import enforce_pr_workflow  # noqa: E402
from hooks.scripts.tests.lib.hook_test_support import HookTestCase  # noqa: E402


class PublicationSessionTests(HookTestCase):
    """Use a supported graph state and a foreign ambient provider session."""

    def test_claude_publication_uses_payload_session_without_provider_env(self) -> None:
        """The hook finds a real graph using its payload session, even with a foreign env session."""
        from packages.tests.graph_manifest_fixture import graph_progress
        from scripts.lib import manifest_policy

        subprocess.run(["git", "init", "-q", "-b", "feature/publication-session", str(self.directory)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.directory),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@test",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "source",
            ],
            check=True,
        )
        temporary_loop = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_loop.cleanup)
        loop = Path(temporary_loop.name)
        graph_progress(self.directory, loop, ["src/**"], session="owner-session")
        seen: list[tuple[str, bool]] = []

        def check_publication(_number: str, _sha: str, *, unit: str = "", progress: str = "") -> None:
            seen.append((os.environ.get("CODERAILS_PUBLICATION_SESSION_ID", ""), manifest_policy.active_graph_unit()))

        payload = {
            "cwd": str(self.directory),
            "session_id": "owner-session",
            "tool_input": {"command": "gh pr merge 42"},
        }
        before = Path.cwd()
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "CLAUDE_AGENTIC_LOOP_DIR": str(loop),
                        "CLAUDE_CODE_SESSION_ID": "",
                        "CODEX_SESSION_ID": "foreign",
                        "CODEX_THREAD_ID": "",
                    },
                ),
                patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
                patch("hooks.scripts.enforce_pr_workflow.git.pr_field", return_value="a" * 40),
                patch(
                    "hooks.scripts.enforce_pr_workflow.publication_gate.enforce",
                    side_effect=check_publication,
                ),
                patch("hooks.scripts.enforce_pr_workflow.config_path", return_value=""),
            ):
                os.environ.pop("CODERAILS_PUBLICATION_SESSION_ID", None)
                enforce_pr_workflow.main()
        finally:
            os.chdir(before)
        self.assertEqual(seen, [("owner-session", True)])

    def test_missing_payload_session_refuses_publication(self) -> None:
        """An empty hook session cannot borrow ambient provider identity."""
        payload = {"cwd": str(self.directory), "tool_input": {"command": "gh pr merge 42"}}
        with (
            patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
            patch("hooks.scripts.enforce_pr_workflow.publication_gate.enforce") as gate,
            patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
        ):
            enforce_pr_workflow.main()
        gate.assert_not_called()
        self.assertIn("session ID", deny.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
