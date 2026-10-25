"""authority.py grant must reject empty, unsubstituted and shell-unsafe session IDs."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "authority.py"


def grant(loops: Path, *session_args: str, session_env: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run `grant` with the ambient session env removed unless session_env is given."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    env |= {"CLAUDE_AGENTIC_LOOP_DIR": str(loops), "PYTHONDONTWRITEBYTECODE": "1"}
    if session_env is not None:
        env["CLAUDE_CODE_SESSION_ID"] = session_env
    cmd = [sys.executable, str(CLI), "grant", *session_args, "--max-prs", "0"]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)


class SessionGuardTests(unittest.TestCase):
    """A failed ${CLAUDE_SESSION_ID} substitution must never produce a grant no hook can see."""

    def test_unsafe_session_is_refused_and_writes_nothing(self) -> None:
        """A placeholder or shell-unsafe ID exits 2 and creates no directory."""
        for placeholder in (
            "${CLAUDE_SESSION_ID}",
            "$CLAUDE_SESSION_ID",
            "{session}",
            "s;echo INJECTED;#",
            "s evil",
            "`id`",
            "?",
            "s?",
        ):
            with self.subTest(placeholder=placeholder), tempfile.TemporaryDirectory() as raw:
                run = grant(Path(raw), "--session", placeholder)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("authority_refused_unsafe_session", run.stderr)
                self.assertEqual(list(Path(raw).iterdir()), [])

    def test_empty_session_without_env_is_refused(self) -> None:
        """An empty --session (or none) with CLAUDE_CODE_SESSION_ID unset refuses and writes nothing."""
        with tempfile.TemporaryDirectory() as raw:
            for args in (("--session", ""), ()):
                with self.subTest(args=args):
                    run = grant(Path(raw), *args)
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn("authority_refused_unsafe_session", run.stderr)
            self.assertEqual(list(Path(raw).iterdir()), [])

    def test_empty_session_falls_back_to_env_and_real_id_grants(self) -> None:
        """Positive control: an empty --session binds to CLAUDE_CODE_SESSION_ID and grants."""
        with tempfile.TemporaryDirectory() as raw:
            run = grant(Path(raw), "--session", "", session_env="abc-123")
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue((Path(raw) / "abc-123/authority.json").is_file())


if __name__ == "__main__":
    unittest.main()
