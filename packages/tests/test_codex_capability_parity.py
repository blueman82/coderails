"""Pin the Codex copy of the capability tools: byte-identical, executable, and honestly instruction-only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"


class CodexCapabilityTests(unittest.TestCase):
    """The Codex package ships the same script and profiles, with weaker (sandbox-only) enforcement."""

    def test_copies_are_byte_identical_and_executable(self) -> None:
        """scripts/capability.py and capabilities/profiles.json are mirrored into the package."""
        for relative in ("scripts/capability.py", "capabilities/profiles.json"):
            with self.subTest(relative=relative):
                self.assertEqual((ROOT / relative).read_bytes(), (CODEX / relative).read_bytes())
        self.assertTrue(os.access(CODEX / "scripts/capability.py", os.X_OK))

    def test_codex_copy_runs_untraced_from_its_own_root(self) -> None:
        """Without the Claude trace library the copy still works, refuses undeclared tests, and writes no rows."""
        with tempfile.TemporaryDirectory() as loop:
            env = {"PATH": os.environ["PATH"], "CLAUDE_AGENTIC_LOOP_DIR": loop, "CLAUDE_SESSION_ID": "s_codex"}
            for tool, args, status in (
                ("repo.inspect", {"op": "list"}, 0),
                ("tests.run", {"name": "not-declared"}, 2),
            ):
                done = subprocess.run(
                    [sys.executable, str(CODEX / "scripts/capability.py"), tool, "--json-args", json.dumps(args)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )
                self.assertEqual(done.returncode, status, done.stdout)
            self.assertEqual(list(Path(loop).iterdir()), [])

    def test_no_codex_hook_claims_per_agent_bash_gating(self) -> None:
        """Codex registers no allowlist hook: per-agent gating there is sandbox_mode plus instruction text only."""
        text = (CODEX / "hooks/hooks.json").read_text(encoding="utf-8")
        self.assertNotIn("reviewer_bash_allowlist", text)
        self.assertNotIn("capability.py", text)


if __name__ == "__main__":
    unittest.main()
