#!/usr/bin/env python3
"""Pin the demoted discipline lints: exit 0, advisory additionalContext, reason_code, outcome=demoted trace row."""

from __future__ import annotations

import json
import os
import runpy
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
    """Every flagged event (SubagentStop, Stop outside a loop) is advisory: exit 0, never a block."""

    def run_hook(
        self,
        name: str,
        text: str,
        directory: str,
        event: str = "SubagentStop",
        session: object = "S_rc",
        **env_extra: str,
    ) -> tuple[subprocess.CompletedProcess[str], str, list[dict[str, Any]]]:
        """Run one hook and return the process, discipline log text, trace rows."""
        env = {
            k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_HOOK_") and k != "CODERAILS_HEADLESS_RUN"
        }
        env.update(CLAUDE_DISCIPLINE_LOG=f"{directory}/discipline.log", CLAUDE_AGENTIC_LOOP_DIR=f"{directory}/state")
        env.update(CLAUDE_HOOK_MAX_ATTEMPTS="1", CLAUDE_HOOK_SLEEP_S="0", **env_extra)
        payload: dict[str, Any] = {"hook_event_name": event, "last_assistant_message": text}
        if session is not None:
            payload["session_id"] = session
        if event == "Stop":
            transcript = Path(directory) / "t.jsonl"
            transcript.write_text(
                json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n"
            )
            payload["transcript_path"] = str(transcript)
            payload["cwd"] = directory
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / f"{name}.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        log = Path(f"{directory}/discipline.log")
        rows: list[dict[str, Any]] = []
        for trace in Path(f"{directory}/state").glob("*/trace.jsonl"):
            rows += [json.loads(line) for line in trace.read_text().splitlines()]
        return result, log.read_text() if log.is_file() else "", rows

    def test_flag_is_advisory_with_reason_code_and_demoted_row(self) -> None:
        """Exit 0, advisory additionalContext, demoted log line with reason_code, one demoted trace row."""
        for name, reason, text in CASES:
            for event in ("SubagentStop", "Stop"):
                with self.subTest(hook=name, event=event), tempfile.TemporaryDirectory() as directory:
                    result, log, rows = self.run_hook(name, text, directory, event)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    out = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(out["hookEventName"], event)
                    self.assertIn("[discipline-advisory]", out["additionalContext"])
                    flagged = [line for line in log.splitlines() if " demoted=1" in line]
                    self.assertEqual(len(flagged), 1)
                    self.assertIn(f"reason_code={reason}", flagged[0])
                    self.assertEqual(sum(" would_block=1" in line for line in log.splitlines()), 1)
                    self.assertIn("blocked=0", flagged[0])
                    self.assertNotIn(" blocked=1", log)
                    self.assertEqual(
                        [(r["command"], r["outcome"], r["reason_code"]) for r in rows], [(name, "demoted", reason)]
                    )

    def test_counters_count_one_event_once(self) -> None:
        """Dedupe control: parse_telemetry reads would_block==1 and demoted==1 per flagged event (not 2x)."""
        measure = runpy.run_path(str(SCRIPTS.parents[1] / "scripts/measure_graph_alignment.py"))

        for name, _, text in CASES:
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as directory:
                self.run_hook(name, text, directory)
                telemetry = measure["parse_telemetry"](Path(f"{directory}/discipline.log"))
                gate = telemetry["gates"][name.replace("check_", "")]
                self.assertEqual((gate["would_block"], gate["demoted"], gate["blocked"]), (1, 1, 0))

    def test_unwritable_trace_store_still_exits_zero(self) -> None:
        """Crash control: the trace row is non-authoritative, so a state dir that is a file cannot change the exit."""
        for name, _, text in CASES:
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as directory:
                Path(f"{directory}/state").write_text("not a directory")
                result, _, rows = self.run_hook(name, text, directory)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("[discipline-advisory]", result.stdout)
                self.assertEqual(rows, [])

    def test_missing_or_unsafe_session_writes_no_row(self) -> None:
        """No session_id, or a path-unsafe one, still advises and exits 0 but writes no trace row."""
        for name, _, text in CASES:
            for session in (None, "../x", "."):
                with self.subTest(hook=name, session=session), tempfile.TemporaryDirectory() as directory:
                    result, _, rows = self.run_hook(name, text, directory, session=session)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(rows, [])
                    self.assertFalse(list(Path(directory).rglob("trace.jsonl")))

    def test_clean_response_writes_no_reason_code(self) -> None:
        """A passing response has no reason_code and no trace row."""
        clean = (
            "ok (verified) " + "y" * 300,
            "all good\n\n## Did Not Verify\n- (unverifiable: prod only) the live behaviour\n",
        )
        for (name, _, _), text in zip(CASES, clean):
            with self.subTest(hook=name), tempfile.TemporaryDirectory() as directory:
                result, log, rows = self.run_hook(name, text, directory)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("reason_code=", log)
                self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
