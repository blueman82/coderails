"""Exercise scripts/installed_parity.py end to end through its command line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "installed_parity.py"


def write(root: Path, relative: str, content: bytes = b"same\n") -> None:
    """Create one file, and any parent directories, under a root."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def parity(*arguments: str, home: str = "/nonexistent-home") -> subprocess.CompletedProcess[str]:
    """Run the tool with a fake HOME so default-location lookup never sees real installs."""
    environment = {**os.environ, "HOME": home}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, check=False, env=environment
    )


class InstalledParityTests(unittest.TestCase):
    """Cover identical, drifted, extra, missing, ignored and packages/codex cases."""

    def setUp(self) -> None:
        """Build a source tree with a Claude file and a packages/codex file."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.source, self.claude, self.codex = base / "src", base / "claude", base / "codex"
        write(self.source, "skills/x/a.py", b"claude-body\n")
        write(self.source, "packages/codex/skills/x/a.py", b"codex-body\n")
        write(self.claude, "skills/x/a.py", b"claude-body\n")
        write(self.codex, "skills/x/a.py", b"codex-body\n")

    def run_parity(self) -> subprocess.CompletedProcess[str]:
        """Compare the fixture installs against the fixture source."""
        return parity(
            "--source-root",
            str(self.source),
            "--claude-installed",
            str(self.claude),
            "--codex-installed",
            str(self.codex),
        )

    def test_identical_trees_pass_and_codex_maps_to_packages_codex(self) -> None:
        """Codex content differs from the Claude path yet matches packages/codex, so this passes."""
        result = self.run_parity()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_byte_drift_fails_and_names_file(self) -> None:
        """A single changed byte in the Claude bundle exits 1 and names bundle and path."""
        write(self.claude, "skills/x/a.py", b"claude-bodY\n")
        result = self.run_parity()
        self.assertEqual(result.returncode, 1)
        self.assertIn("claude", result.stdout)
        self.assertIn("skills/x/a.py", result.stdout)

    def test_codex_drift_is_judged_against_packages_codex(self) -> None:
        """A Codex file equal to the root copy but not the packages/codex copy is drift."""
        write(self.codex, "skills/x/a.py", b"claude-body\n")
        result = self.run_parity()
        self.assertEqual(result.returncode, 1)
        self.assertIn("codex", result.stdout)

    def test_extra_installed_file_fails(self) -> None:
        """A file only in the installed tree is a difference."""
        write(self.codex, "skills/x/extra.py")
        result = self.run_parity()
        self.assertEqual(result.returncode, 1)
        self.assertIn("skills/x/extra.py", result.stdout)

    def test_ignored_files_do_not_count(self) -> None:
        """__pycache__, .pyc and .DS_Store never count as differences."""
        write(self.claude, "skills/x/__pycache__/a.cpython-39.pyc")
        write(self.claude, "skills/x/b.pyc")
        write(self.claude, ".DS_Store")
        write(self.codex, "skills/.DS_Store")
        result = self.run_parity()
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_missing_directory_exits_two(self) -> None:
        """A given installed directory that does not exist is a usage error, not a pass."""
        result = parity("--source-root", str(self.source), "--claude-installed", str(self.claude / "nope"))
        self.assertEqual(result.returncode, 2)

    def test_not_installed_defaults_skip_with_exit_zero(self) -> None:
        """With no flags and no installed copies the tool says so and exits 0."""
        result = parity("--source-root", str(self.source), home=self.temporary.name)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("not installed, skipped"), 2)

    def test_default_locations_are_discovered(self) -> None:
        """Defaults resolve the Claude installPath and the Codex plugin cache under HOME."""
        home = Path(self.temporary.name) / "home"
        write(
            home,
            ".claude/plugins/installed_plugins.json",
            json.dumps({"plugins": {"coderails@coderails": [{"installPath": str(self.claude)}]}}).encode(),
        )
        write(home, ".codex/plugins/cache/coderails/coderails-codex/0.2.0/skills/x/a.py", b"codex-DRIFT\n")
        result = parity("--source-root", str(self.source), home=str(home))
        self.assertEqual(result.returncode, 1)
        self.assertIn("codex", result.stdout)
        self.assertNotIn("DIFF claude", result.stdout)


if __name__ == "__main__":
    unittest.main()
