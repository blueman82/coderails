"""memory_dir.py: the memory directory for a working directory, derived the way Claude Code names project folders."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/memory_dir.py"


def run(*arguments: str, home: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI with a chosen HOME."""
    env = {**os.environ, "HOME": home}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments], env=env, capture_output=True, text=True, check=False
    )


class MemoryDirTests(unittest.TestCase):
    """Slug = realpath with every non-alphanumeric character as `-`; provider picks ~/.claude or ~/.codex."""

    def test_documented_value_for_an_ordinary_path(self) -> None:
        """/Users/x/Github/proj becomes -Users-x-Github-proj under ~/.claude/projects/<slug>/memory."""
        with tempfile.TemporaryDirectory() as home:
            result = run("--cwd", "/Users/x/Github/proj", home=home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"{home}/.claude/projects/-Users-x-Github-proj/memory")

    def test_symlink_is_resolved_and_dots_and_underscores_become_hyphens(self) -> None:
        """The slug comes from the realpath; `.` and `_` are hyphenated as the real project folders show."""
        with tempfile.TemporaryDirectory() as home:
            target = Path(home).resolve() / "my_proj.d"
            target.mkdir()
            link = Path(home).resolve() / "link"
            link.symlink_to(target)
            out = run("--cwd", str(link), "--provider", "codex", home=home).stdout.strip()
            self.assertTrue(out.endswith("-my-proj-d/memory"), out)
            self.assertIn("/.codex/projects/", out)

    def test_unknown_provider_is_refused(self) -> None:
        """Argparse rejects anything but claude or codex."""
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(run("--provider", "x", home=home).returncode, 2)


if __name__ == "__main__":
    unittest.main()
