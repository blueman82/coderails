"""Exercise the maintained quality CLI with real configured checkers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECK = ROOT / "scripts/quality/check.py"


class QualityCliTests(unittest.TestCase):
    """Preserve tool enforcement and Markdown-only changed-scan contracts."""

    def invoke(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run only the isolated fixture source selection through real required tools."""
        return subprocess.run(
            [sys.executable, str(CHECK), "--root", str(root), *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_docstring_and_formatted_positive(self) -> None:
        """A compliant module passes and the missing-docstring negative control fails."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "example.py"
            module.write_text(
                '"""Compliant fixture."""\n\n\ndef label(value: str) -> str:\n'
                '    """Return the label."""\n    return value.strip()\n'
            )
            result = self.invoke(root, "--strict", "--paths", str(module))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            module.write_text('"""Fixture."""\n\n\ndef label(value: str) -> str:\n    return value.strip()\n')
            result = self.invoke(root, "--strict", "--paths", str(module))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("D103", result.stdout + result.stderr)

    def test_json_output_is_pure_json_with_structured_findings(self) -> None:
        """--json prints one JSON object even when the external tools fail and write to stdout."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "bad.py"
            module.write_text("x = 1 \n")
            result = self.invoke(root, "--json", "--paths", str(module))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(result.stdout)
            self.assertEqual(data["scanned"], 1)
            self.assertFalse(data["external_ok"], "ruff/black must reject the fixture")
            self.assertEqual(
                [(Path(f["path"]).name, f["line"], f["message"]) for f in data["findings"]],
                [("bad.py", 1, "trailing whitespace")],
            )

    def test_json_clean_file_has_no_findings(self) -> None:
        """A compliant file reports no findings and external_ok true."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "ok.py"
            module.write_text('"""Compliant fixture."""\n\nVALUE = 1\n')
            data = json.loads(self.invoke(root, "--json", "--paths", str(module)).stdout)
            self.assertEqual((data["scanned"], data["findings"], data["external_ok"]), (1, [], True))

    def test_changed_markdown_only(self) -> None:
        """A Git repository whose only changed file is Markdown needs no source tools."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            for arguments in (
                ("init", "-q"),
                ("config", "user.name", "Fixture"),
                ("config", "user.email", "fixture@example.invalid"),
            ):
                subprocess.run(["git", *arguments], cwd=root, env=environment, check=True, capture_output=True)
            note = root / "note.md"
            note.write_text("baseline\n")
            subprocess.run(["git", "add", "."], cwd=root, env=environment, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"], cwd=root, env=environment, check=True, capture_output=True
            )
            note.write_text("changed\n")
            result = self.invoke(root, "--strict", "--changed")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
