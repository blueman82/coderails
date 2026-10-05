"""detect_test_command.py: the ordered detection list from commands/test-gate-setup.md, as JSON."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/detect_test_command.py"


def detect(files: dict[str, str]) -> dict[str, object]:
    """Create the files in a temp project and return the script's JSON."""
    with tempfile.TemporaryDirectory() as directory:
        for name, text in files.items():
            Path(directory, name).write_text(text)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--dir", directory], capture_output=True, text=True, check=False
        )
    assert result.returncode == 0, result.stderr
    data: dict[str, object] = json.loads(result.stdout)
    return data


class DetectTests(unittest.TestCase):
    """Each marker maps to its command; several markers keep the documented order and leave `command` null."""

    def test_each_marker(self) -> None:
        """One file gives one candidate and that command."""
        cases = (
            ({"package.json": '{"scripts": {"test": "jest"}}'}, "npm test"),
            ({"Cargo.toml": ""}, "cargo test"),
            ({"pyproject.toml": ""}, "pytest -x"),
            ({"setup.cfg": ""}, "pytest -x"),
            ({"go.mod": ""}, "go test ./..."),
            ({"Makefile": "build:\n\ttrue\n\ntest:\n\ttrue\n"}, "make test"),
            ({"mix.exs": ""}, "mix test"),
            ({"Gemfile": ""}, "bundle exec rspec"),
        )
        for files, expected in cases:
            with self.subTest(expected=expected):
                result = detect(files)
                self.assertEqual((result["command"], result["candidates"]), (expected, [expected]))

    def test_markers_without_a_test_target_are_not_candidates(self) -> None:
        """package.json with no test script and a Makefile with no test target detect nothing."""
        result = detect({"package.json": '{"scripts": {"build": "x"}}', "Makefile": "build:\n\ttrue\n"})
        self.assertEqual((result["command"], result["candidates"]), (None, []))
        self.assertEqual(detect({"package.json": "{not json"})["candidates"], [])

    def test_several_markers_keep_the_documented_order_and_ask(self) -> None:
        """Ambiguity: all candidates in list order, no single command."""
        result = detect({"go.mod": "", "Cargo.toml": "", "Gemfile": ""})
        self.assertEqual(result["candidates"], ["cargo test", "go test ./...", "bundle exec rspec"])
        self.assertIsNone(result["command"])


class WiringTests(unittest.TestCase):
    """The command, the Codex skill and memory-consolidation call the scripts instead of describing the procedure."""

    def test_prose_calls_the_scripts(self) -> None:
        """Each caller names its script."""
        for relative, needle in (
            ("commands/test-gate-setup.md", "scripts/detect_test_command.py"),
            ("packages/codex/skills/test-gate-setup/SKILL.md", "scripts/detect_test_command.py"),
            ("skills/memory-consolidation/SKILL.md", "scripts/memory_dir.py"),
            ("packages/codex/skills/memory-consolidation/SKILL.md", "scripts/memory_dir.py"),
        ):
            with self.subTest(file=relative):
                self.assertIn(needle, (REPO / relative).read_text())
        self.assertNotIn("`mix.exs` → use", (REPO / "commands/test-gate-setup.md").read_text())


if __name__ == "__main__":
    unittest.main()
