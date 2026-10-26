#!/usr/bin/env python3
"""Claude completion rechecks old and new driver evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_dispatch


class DriverCompletionTests(unittest.TestCase):
    """Exercise the native-to-driver evidence boundary."""

    def test_claude_completion_validates_the_sealed_native_snapshot(self) -> None:
        """The old graph is checked as history, while new attempts use driver evidence."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
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
                patch.object(graph_dispatch, "validate_state"),
                patch("hooks.scripts.lib.graph_dispatch.graph_semantics.can_complete", return_value={"eligible": True}),
                patch.object(graph_dispatch, "revalidate_all") as native,
            ):
                graph_dispatch.validate_graph_state_completion(path, state, "S")
            native.assert_called_once_with(old)


if __name__ == "__main__":
    unittest.main()
