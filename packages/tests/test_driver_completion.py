"""Driver completion must re-read old and new worker evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
from graph_completion import validate_completion_state


class DriverCompletionTests(unittest.TestCase):
    """Keep native history distinct from driver attempts at completion."""

    def test_codex_completion_validates_the_sealed_native_snapshot(self) -> None:
        """Pending old nodes do not become a completed-native requirement."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            external = Path(directory) / "external"
            external.mkdir()
            evals_path = external / "evals.json"
            old: dict[str, Any] = {
                "session_id": "S",
                "loop_id": "L",
                "revision": 1,
                "graph": {"nodes": {}, "dispatches": {}},
            }
            raw = json.dumps(old).encode()
            path.with_name("progress.json.pre-driver").write_bytes(raw)
            state: dict[str, Any] = {
                "session_id": "S",
                "loop_id": "L",
                "revision": 3,
                "graph": {
                    "dispatch_mode": "driver",
                    "native_last_revision": 1,
                    "driver_from_revision": 3,
                    "native_backup_sha256": hashlib.sha256(raw).hexdigest(),
                    "nodes": {},
                    "dispatches": {},
                    "active_wave": None,
                },
            }
            with (
                patch("graph_completion.graph_semantics.can_complete", return_value={"eligible": True}) as _ready,
                patch("graph_completion.validate_work_units"),
                patch("graph_completion.validate_worker_evidence") as native,
                patch("graph_completion.validate_completion_evidence"),
            ):
                validate_completion_state(path, state, "S", 3, evals_path, path, path, None)
            native.assert_called_once_with(old, require_complete=False)


if __name__ == "__main__":
    unittest.main()
