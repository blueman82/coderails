"""Codex graph_io.write stamps updated_at on progress.json writes (and only there)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))
import graph_io  # noqa: E402


class UpdatedAtTests(unittest.TestCase):
    """The stamp is part of the written bytes and does not mutate the caller's dict."""

    def test_progress_json_is_stamped_other_files_are_not(self) -> None:
        """progress.json gains updated_at; a sibling artifact is written verbatim."""
        with tempfile.TemporaryDirectory() as directory:
            progress, other = Path(directory) / "progress.json", Path(directory) / "retro.json"
            state = {"schema_version": 3}
            graph_io.write(progress, state, create=True)
            graph_io.write(other, state, create=True)
            self.assertRegex(json.loads(progress.read_text())["updated_at"], r"^\d{4}-\d\d-\d\dT")
            self.assertNotIn("updated_at", json.loads(other.read_text()))
            self.assertEqual(state, {"schema_version": 3})


if __name__ == "__main__":
    unittest.main()
