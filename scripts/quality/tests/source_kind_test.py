"""Prevent extensionless Python entrypoints from disappearing from quality enforcement."""

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.quality import check, quality_tools


class SourceKindTests(unittest.TestCase):
    """Exercise both source validation and required tools against shebang-only files."""

    def test_bad_extensionless_python_is_discovered_and_checked(self) -> None:
        """An invalid maintained hook must fail even when it has no filename suffix."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "scripts/git-hooks/pre-commit"
            path.parent.mkdir(parents=True)
            path.write_text("#!/usr/bin/env python3\n# import os\nreturn value = 1\n")
            self.assertIn(path.resolve(), check.source_files(root, []))
            errors = io.StringIO()
            with (
                patch.object(sys, "argv", ["check.py", "--strict", "--root", directory, "--paths", str(path)]),
                patch.object(check, "external_checks", return_value=True),
                redirect_stdout(io.StringIO()),
                redirect_stderr(errors),
            ):
                self.assertEqual(check.main(), 1)
            self.assertIn("invalid Python", errors.getvalue())
            self.assertIn("commented-out code", errors.getvalue())

    def test_extensionless_python_receives_all_required_tools(self) -> None:
        """Ruff, Black, Pyright and mypy must all receive the actual entrypoint path."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "entrypoint"
            path.write_text('#!/usr/bin/python3\n"""Fixture."""\n')
            with (
                patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)),
                patch.object(quality_tools, "run_tool", return_value=True) as run,
            ):
                self.assertTrue(quality_tools.python_checks([path], root, root / "pyproject.toml"))
            self.assertEqual(len(run.call_args_list), 4)
            for call in run.call_args_list:
                self.assertIn(str(path), call.args[0])


if __name__ == "__main__":
    unittest.main()
