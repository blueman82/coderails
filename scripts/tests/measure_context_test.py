"""Verify the context counters in the graph-alignment measurement script."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "measure_graph_alignment.py"


class ContextCountTests(unittest.TestCase):
    """Run the CLI against an empty root with an isolated HOME."""

    def test_context_counts_dedupe_by_event_id_and_ignore_other_commands(self) -> None:
        """Manifest/route rows count once per event_id by command/reason; unrelated and torn rows never inflate it."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "repo").mkdir()
            manifest = {"event_id": "m1", "command": "context_manifest", "outcome": "ok", "reason_code": "manifest_ok"}
            torn = {"event_id": "m2", "command": "context_manifest", "outcome": "fail_open"}
            route = {"event_id": "r1", "command": "context_route", "outcome": "ok", "reason_code": "route_match"}
            other = {"event_id": "g1", "command": "gate", "outcome": "blocked", "reason_code": "r1"}
            rows = "\n".join(json.dumps(r) for r in (manifest, manifest, route, other, torn)) + "\n{torn"
            log = base / "home/.coderails/agentic-loop/s1/trace.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(rows, encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if "AGENTIC_LOOP" not in k and k != "PLUGIN_DATA"}
            env["HOME"] = str(base / "home")
            command = [sys.executable, str(SCRIPT), "--root", str(base / "repo"), "--json"]
            done = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            counts = json.loads(done.stdout)["context"]
        self.assertEqual(counts["by_reason"], {"context_manifest/manifest_ok": 1, "context_route/route_match": 1})
        self.assertEqual((counts["events"], counts["duplicates"], counts["malformed"]), (2, 1, 2))


if __name__ == "__main__":
    unittest.main()
