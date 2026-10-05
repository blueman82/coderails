"""Verify the external_enforcement counter block of measure_graph_alignment.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class EnforcementCountTests(unittest.TestCase):
    """Run the CLI against the real repo root with an isolated HOME."""

    def test_external_enforcement_counts_dedupe_by_event_id(self) -> None:
        """Rows from external_enforcement/ci_verify count once per event_id; foreign commands are malformed."""
        row = {"event_id": "e1", "command": "ci_verify.run", "outcome": "refused", "reason_code": "SHA_MISMATCH"}
        rows = [row, row, {**row, "event_id": "e2", "command": "external_enforcement.apply", "reason_code": "NO_YES"}]
        rows.append({**row, "event_id": "e3", "command": "other"})
        with tempfile.TemporaryDirectory() as home:
            trace = Path(home) / ".coderails/agentic-loop/external-enforcement/trace.jsonl"
            trace.parent.mkdir(parents=True)
            trace.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if "AGENTIC_LOOP" not in k and k != "PLUGIN_DATA"}
            env["HOME"] = home
            script = str(REPO / "scripts" / "measure_graph_alignment.py")
            run = subprocess.run(
                [sys.executable, script, "--root", str(REPO), "--json"],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
        counts = json.loads(run.stdout)["external_enforcement"]
        self.assertEqual((counts["events"], counts["duplicates"], counts["malformed"]), (2, 1, 2))
        self.assertEqual(counts["by_reason"], {"ci_verify.run/SHA_MISMATCH": 1, "external_enforcement.apply/NO_YES": 1})


if __name__ == "__main__":
    unittest.main()
