"""Exercise strict Python quality enforcement and independent materialization checks."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.quality import check, quality_tools


class QualityTests(unittest.TestCase):
    """Require real tool availability and catch source-level control failures."""

    def test_required_tool_missing_fails(self) -> None:
        """A missing required checker must never silently degrade strict coverage."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temporary)
            path = root / "good.py"
            path.write_text('"""Good module."""\n')
            with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess(["python"], 1)):
                self.assertFalse(quality_tools.python_checks([path], root, root / "pyproject.toml"))

    def test_python_file_length_is_not_exempt(self) -> None:
        """Enforce the same file ceiling on Python as every other runtime language."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            root = Path(temporary)
            (root / "long.py").write_text('"""Large module."""\n' + "\n" * 401)
            with (
                patch.object(sys, "argv", ["check.py", "--strict", "--root", temporary]),
                patch.object(check, "external_checks", return_value=True),
            ):
                self.assertEqual(check.main(), 1)

    def test_function_and_format_controls(self) -> None:
        """Reject overlong functions, missing final newlines and invalid JSON."""
        self.assertTrue(check.check_python(Path("bad.py"), "def f():\n" + "    pass\n" * 101, 100))
        self.assertTrue(check.check_format(Path("bad.json"), "{"))
        self.assertTrue(check.check_format(Path("bad.py"), "x = 1 "))
        self.assertTrue(check.check_commented_code(Path("bad.py"), "# import os\n"))

    def test_external_path_is_checked_in_warn_mode(self) -> None:
        """Hooks can inspect a selected temporary file outside the repository."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.py"
            path.write_text("bad \n")
            errors = io.StringIO()
            with (
                patch.object(sys, "argv", ["check.py", "--paths", str(path)]),
                patch.object(check, "external_checks", return_value=True),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(errors),
            ):
                self.assertEqual(check.main(), 0)
            self.assertIn("trailing whitespace", errors.getvalue())

    def test_commented_code_distinguishes_prose(self) -> None:
        """Retain the source checker's documented prose and command boundaries."""
        for text in (
            "# return value = 1\n",
            "# git merge conflict-resolution operations are exempt\n",
            "#   git push --force origin main\n",
        ):
            self.assertEqual(check.check_commented_code(Path("example.py"), text), [])
        for text in ("# def removed():\n", "# git status --short\n", '# echo "removed"\n', "# return 1\n"):
            self.assertTrue(check.check_commented_code(Path("example.py"), text))
        self.assertTrue(check.check_python(Path("bad.py"), "return value = 1\n", 100))

    def test_generated_semantics_cannot_drift(self) -> None:
        """Require both independently installed copies to match the maintained source."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temporary)
            source = root / "packages/graph-semantics/graph_semantics.py"
            source.parent.mkdir(parents=True)
            source.write_text('"""Semantics."""\n')
            self.assertFalse(quality_tools.check_materialization(root))
            for relative in quality_tools.GENERATED_SEMANTICS:
                target = root / relative
                target.parent.mkdir(parents=True)
                target.write_bytes(source.read_bytes())
            self.assertTrue(quality_tools.check_materialization(root))
            (root / quality_tools.GENERATED_SEMANTICS[0]).write_text("different\n")
            self.assertFalse(quality_tools.check_materialization(root))


if __name__ == "__main__":
    unittest.main()
