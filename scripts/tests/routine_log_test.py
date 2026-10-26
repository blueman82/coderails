"""routine_log.py emit: closed outcome enum, closed per-routine reason codes, derived legacy marker line."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TextIO, cast
from unittest import mock

from packages.codex.scripts import routine_log as codex_routine_log
from scripts import routine_log

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "scripts" / "routine_log.py"
MARKERS = {
    ("run_ok", ""): "run=ok",
    ("run_abort", "docs_sync_deny"): "abort=docs_sync_deny",
    ("run_refused", "merge"): "refused=merge",
    ("run_incomplete", "incomplete-run"): "abort=incomplete-run",
}


def emit(
    directory: Path, *extra: str, routine: str = "docs-sync", run_id: str = "r1"
) -> subprocess.CompletedProcess[str]:
    """Run `routine_log.py emit` against files in directory; extra holds --outcome and --reason-code."""
    argv = [sys.executable, str(TOOL), "emit", "--log", str(directory / "x.jsonl"), "--run-id", run_id]
    argv += ["--routine", routine, "--stage", "merge", *extra]
    env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": str(directory / "loop"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(argv, capture_output=True, text=True, env=env)


class EmitTests(unittest.TestCase):
    """Rows are appended only for members of the closed enums; the human marker derives from the row."""

    def setUp(self) -> None:
        """Give each test its own directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def rows(self) -> list[dict[str, str]]:
        """The JSONL rows written so far."""
        path = self.dir / "x.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_row_shape_and_derived_marker(self) -> None:
        """Each terminal outcome writes a v1 row and exactly the legacy marker; only run_ok yields run=ok."""
        for (outcome, code), marker in MARKERS.items():
            with self.subTest(outcome=outcome):
                args = ["--outcome", outcome] + (["--reason-code", code] if code else [])
                self.assertEqual(emit(self.dir, *args).returncode, 0)
                row = self.rows()[-1]
                self.assertEqual(
                    (row["v"], row["run_id"], row["routine"], row["stage"], row["outcome"], row["reason_code"]),
                    (1, "r1", "docs-sync", "merge", outcome, code),
                )
                self.assertIn("ts", row)
                last = (self.dir / "x.log").read_text().splitlines()[-1]
                self.assertTrue(last.endswith(marker), last)
                self.assertEqual("run=ok" in last, outcome == "run_ok")

    def test_stage_ok_writes_no_terminal_marker(self) -> None:
        """A stage_ok row derives a stage line that no last-marker predicate can mistake for a terminal."""
        self.assertEqual(emit(self.dir, "--outcome", "stage_ok").returncode, 0)
        line = (self.dir / "x.log").read_text()
        self.assertNotRegex(line, r"run=ok|abort=|refused=|delivery=started")

    def test_invented_outcome_is_refused_and_appends_nothing(self) -> None:
        """Negative control: the historical invented marker is exit 2 with no row and no log line."""
        result = emit(self.dir, "--outcome", "merge-blocked", "--reason-code", "integrity-review-pending")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse((self.dir / "x.jsonl").exists())
        self.assertFalse((self.dir / "x.log").exists())

    def test_invented_reason_code_and_misplaced_code_are_refused(self) -> None:
        """A code outside the list, a code on run_ok and an unknown routine all exit 2 with nothing written."""
        cases = (
            ("--outcome", "run_abort", "--reason-code", "made_up"),
            ("--outcome", "run_ok", "--reason-code", "merge"),
            ("--outcome", "run_abort"),
        )
        for args in cases:
            with self.subTest(args=args):
                self.assertEqual(emit(self.dir, *args).returncode, 2)
        self.assertEqual(emit(self.dir, "--outcome", "run_ok", routine="no-such").returncode, 2)
        self.assertEqual(emit(self.dir, "--outcome", "run_ok", routine="../x").returncode, 2)
        self.assertFalse((self.dir / "x.jsonl").exists())

    def test_loop_retro_codes_are_its_own_list(self) -> None:
        """Codes are per routine: a docs-sync-only code is refused for loop-retro-promotion."""
        retro = "loop-retro-promotion"
        ok = emit(self.dir, "--outcome", "run_abort", "--reason-code", "too_many_paths", routine=retro)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = emit(self.dir, "--outcome", "run_abort", "--reason-code", "docs_sync_deny", routine=retro)
        self.assertEqual(bad.returncode, 2)

    def test_unwritable_human_log_does_not_append_a_jsonl_terminal(self) -> None:
        """Opening both log destinations precedes either append under the existing lock."""
        (self.dir / "x.log").mkdir()
        result = emit(self.dir, "--outcome", "run_ok")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("log_unwritable", result.stderr)
        self.assertEqual(self.rows(), [])

    def test_failed_human_append_refuses_both_provider_emits(self) -> None:
        """A write failure after both files open returns log_unwritable for both providers."""
        original_open = Path.open

        class BrokenHuman:
            def __init__(self, stream: TextIO) -> None:
                self.stream = stream

            def __enter__(self) -> BrokenHuman:
                return self

            def __exit__(self, *args: object) -> None:
                self.stream.close()

            def write(self, value: str) -> None:
                raise OSError("ENOSPC")

        for name, module in (("claude", routine_log), ("codex", codex_routine_log)):
            with self.subTest(provider=name):
                log, human = self.dir / name / "x.jsonl", self.dir / name / "x.log"
                self.assertEqual(
                    module.emit(log, "r0", "docs-sync", "begin", "run_incomplete", "incomplete-run", human), ""
                )

                def broken_open(
                    path: Path, mode: str = "r", *, encoding: str | None = None, human_path: Path = human
                ) -> TextIO | BrokenHuman:
                    stream = cast(TextIO, original_open(path, mode, encoding=encoding))
                    return BrokenHuman(stream) if path == human_path else stream

                with mock.patch.object(Path, "open", broken_open):
                    refusal = module.emit(log, "r1", "docs-sync", "merge", "run_ok", human_log=human)
                self.assertEqual(refusal, "log_unwritable")
                outcomes = [json.loads(line)["outcome"] for line in log.read_text().splitlines()]
                self.assertEqual(outcomes, ["run_incomplete", "run_ok"])
                self.assertTrue(human.read_text().splitlines()[-1].endswith("abort=incomplete-run"))

    def test_unknown_merge_uses_unknown_human_marker(self) -> None:
        """The uncertain-merge JSONL reason gets the matching human marker."""
        result = emit(self.dir, "--outcome", "run_incomplete", "--reason-code", "merge_state_unknown")
        self.assertEqual(result.returncode, 0)
        self.assertTrue((self.dir / "x.log").read_text().splitlines()[-1].endswith("incomplete=merge-unknown"))


if __name__ == "__main__":
    unittest.main()
