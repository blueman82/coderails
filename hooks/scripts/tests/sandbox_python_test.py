"""Check sandbox policy substitution and launch safeguards without launching srt."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.sandbox import render_settings, sandbox_probe, spawn_sandboxed_worker


class SandboxPythonTests(unittest.TestCase):
    """Preserve allow-only policy, executable denies and pre-launch refusal."""

    def test_json_paths_and_denies(self) -> None:
        """Path punctuation stays data and does not inject extra allow entries."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            worktree = root / 'work|"\\tree'
            scratch = root / "scratch"
            primary = root / "primary.git"
            home = root / "home"
            for path in (worktree, scratch, primary, home):
                path.mkdir()
            output = root / "settings.json"
            with (
                patch.dict(os.environ, {"HOME": str(home), "TMPDIR": str(scratch) + "/"}),
                patch.object(shutil, "which", return_value="/fixture/rg"),
            ):
                render_settings.render_settings(str(worktree), str(scratch), str(primary), str(output))
            data = json.loads(output.read_text())
            self.assertIn(str(worktree), data["filesystem"]["allowWrite"])
            self.assertEqual(len(data["filesystem"]["allowWrite"]), 7)
            for path in (primary / "hooks", primary / "config", home / ".claude/hooks", home / ".claude/plugins"):
                self.assertIn(str(path), data["filesystem"]["denyWrite"])
            self.assertEqual(data["filesystem"]["denyRead"], [])
            self.assertNotIn("*", data["network"]["allowedDomains"])
            state = Path(f"/private/tmp/claude-{os.getuid()}") / str(worktree).replace("/", "-")
            state.rmdir()

    def test_bad_input_never_writes_policy(self) -> None:
        """Refuse missing or relative paths before creating a settings file."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "settings.json"
            with self.assertRaises(ValueError):
                render_settings.render_settings("relative", temporary, temporary, str(output))
            self.assertFalse(output.exists())

    def test_guard_denial_precedes_scratch(self) -> None:
        """A denied native worker cannot allocate scratch or call npx."""
        with tempfile.TemporaryDirectory() as temporary:
            prompt = Path(temporary) / "prompt"
            prompt.write_text("worker instructions")
            denial = subprocess.CompletedProcess(
                ["python"],
                0,
                '{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"freeze required"}}',
                "",
            )
            with (
                patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "session"}),
                patch.object(subprocess, "run", return_value=denial) as run,
                patch.object(tempfile, "mkdtemp") as scratch,
                patch.object(Path, "is_file", return_value=True),
            ):
                with self.assertRaisesRegex(ValueError, "freeze required"):
                    spawn_sandboxed_worker.launch(temporary, str(prompt), "sonnet")
                self.assertEqual(run.call_count, 1)
                scratch.assert_not_called()
                payload = json.loads(run.call_args.kwargs["input"])
                self.assertIn("spawn_sandboxed_worker.py", payload["tool_input"]["command"])

    def test_bare_probe_rejects_successful_escape(self) -> None:
        """Outside writes distinguish an uncontained probe from real enforcement."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temporary)
            worktree = root / "repo"
            home = root / "home"
            worktree.mkdir()
            home.mkdir()
            subprocess.run(["git", "init", "-q", str(worktree)], check=True)
            with patch.dict(os.environ, {"HOME": str(home)}):
                self.assertEqual(sandbox_probe.probe(worktree), 2)
            self.assertFalse((home / ".sandbox-escape-probe").exists())
            self.assertFalse((root / "escape-probe").exists())
            with patch.object(sandbox_probe, "probe_write", side_effect=[True, False, False]):
                self.assertEqual(sandbox_probe.probe(worktree), 0)


if __name__ == "__main__":
    unittest.main()
