#!/usr/bin/env python3
"""Pin stable reason codes on the discipline gates' block lines and trace rows (exit codes stay unchanged)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1]
CASES = (
    ("check_confidence_labels", "confidence_label_missing", "x" * 300),
    ("check_verify_loop", "verify_loop_missing", "done\n\n## Did Not Verify\n- the thing I could have checked\n"),
)


class DisciplineReasonCodeTests(unittest.TestCase):
    """SubagentStop is the never-demoted path, so a block is deterministic without a transcript."""

    def run_hook(self, name: str, text: str, directory: str) -> tuple[int, str, list[dict[str, Any]]]:
        """Run one hook and return exit code, discipline log text, trace rows."""
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_HOOK_") and k != "CODERAILS_HEADLESS_RUN"
        }
        env.update(CLAUDE_DISCIPLINE_LOG=f"{directory}/discipline.log", CLAUDE_AGENTIC_LOOP_DIR=f"{directory}/state")
        payload = {"hook_event_name": "SubagentStop", "session_id": "S_rc", "last_assistant_message": text}
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / f"{name}.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        log = Path(f"{directory}/discipline.log")
        trace = Path(f"{directory}/state/S_rc/trace.jsonl")
        rows = [json.loads(line) for line in trace.read_text().splitlines()] if trace.is_file() else []
        return result.returncode, log.read_text() if log.is_file() else "", rows

    def test_block_carries_reason_code_and_trace_row(self) -> None:
        """Exit stays 2; the blocked log line keeps its counted fields and gains reason_code; one trace row."""
        for name, reason, text in CASES:
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as directory:
                code, log, rows = self.run_hook(name, text, directory)
                self.assertEqual(code, 2)
                blocked = [line for line in log.splitlines() if " blocked=1" in line]
                self.assertEqual(len(blocked), 1)
                self.assertIn(f"reason_code={reason}", blocked[0])
                self.assertEqual(
                    [(r["command"], r["outcome"], r["reason_code"]) for r in rows], [(name, "blocked", reason)]
                )

    def test_clean_response_writes_no_reason_code(self) -> None:
        """A passing response has no reason_code and no trace row."""
        clean = (
            "ok (verified) " + "y" * 300,
            "all good\n\n## Did Not Verify\n- (unverifiable: prod only) the live behaviour\n",
        )
        for (name, _, _), text in zip(CASES, clean):
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as directory:
                code, log, rows = self.run_hook(name, text, directory)
                self.assertEqual(code, 0)
                self.assertNotIn("reason_code=", log)
                self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
