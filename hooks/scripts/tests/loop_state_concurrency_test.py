"""Claude-local progress.json updates must not lose writes or leave partial state."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_state_common import atomic_progress_update


class AtomicProgressUpdateTests(unittest.TestCase):
    """The mkdir lock plus atomic replace is the sole Claude state transaction boundary."""

    def setUp(self) -> None:
        """Create a state file and generous lock retry settings for contended writers."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "progress.json"
        self.path.write_text(json.dumps({"schema_version": 3, "counter": 0}), encoding="utf-8")
        environment = patch.dict(os.environ, {"CLAUDE_HOOK_MAX_ATTEMPTS": "2000", "CLAUDE_HOOK_SLEEP_S": "0.002"})
        environment.start()
        self.addCleanup(environment.stop)

    def read(self) -> dict[str, Any]:
        """Return the persisted state."""
        value: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        return value

    def test_concurrent_writers_lose_no_updates(self) -> None:
        """Every one of many concurrent read-modify-write updates must land exactly once."""

        def bump(state: dict[str, Any]) -> dict[str, Any]:
            return {**state, "counter": state["counter"] + 1}

        def attempt(_: int) -> bool:
            return atomic_progress_update(self.path, bump)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(40)))
        self.assertTrue(all(results))
        self.assertEqual(self.read()["counter"], 40)
        self.assertFalse(Path(f"{self.path}.lock").exists())
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["progress.json"])

    def test_failed_update_leaves_file_unchanged_and_releases_lock(self) -> None:
        """A transform that raises or returns an unwritable value must not mutate state or strand the lock."""
        before = self.path.read_bytes()

        def explode(_: dict[str, Any]) -> dict[str, Any]:
            raise KeyError("boom")

        def unserialisable(state: dict[str, Any]) -> dict[str, Any]:
            return {**state, "bad": {1, 2}}

        self.assertFalse(atomic_progress_update(self.path, explode))
        self.assertFalse(atomic_progress_update(self.path, unserialisable))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(f"{self.path}.lock").exists())
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["progress.json"])

    def test_unavailable_lock_refuses_without_writing(self) -> None:
        """A held lock past the retry budget returns False and leaves the file byte-identical."""
        Path(f"{self.path}.lock").mkdir()
        with patch.dict(os.environ, {"CLAUDE_HOOK_MAX_ATTEMPTS": "2", "CLAUDE_HOOK_SLEEP_S": "0.001"}):
            self.assertFalse(atomic_progress_update(self.path, lambda state: {**state, "counter": 99}))
        self.assertEqual(self.read()["counter"], 0)


if __name__ == "__main__":
    unittest.main()
