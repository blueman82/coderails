"""Codex native session variables bind memory citations to the caller."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.tests.fake_muninn_case import PROMPT, SESSION, StoreCase

ADAPTER = Path(__file__).resolve().parents[1] / "lib/memory_adapter.py"


class CodexSessionTests(StoreCase):
    """Use the fake store and synthetic transcript with no Claude session variable."""

    with_store = True

    def test_native_session_defaults_to_caller(self) -> None:
        """Quote-only and explicit cites work with either Codex native session variable."""
        env = dict(os.environ)
        for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "CODEX_THREAD_ID"):
            env.pop(key, None)
        for native_var in ("CODEX_SESSION_ID", "CODEX_THREAD_ID"):
            env[native_var] = SESSION
            for cite_args in (("--quote", PROMPT), ("--cite", f"claude:{SESSION}:1.1", "--quote", PROMPT)):
                with self.subTest(native_var=native_var, cite_args=cite_args):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(ADAPTER),
                            "add",
                            "--scope",
                            "loop",
                            "--loop",
                            "L1",
                            "--type",
                            "lesson",
                            "--claim",
                            "Codex caller lesson",
                            *cite_args,
                        ],
                        capture_output=True,
                        text=True,
                        env=env,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            env.pop(native_var)
        self.assertEqual(len(self.listed()), 4)


if __name__ == "__main__":
    import unittest

    unittest.main()
