"""Verify the dispatch-envelope counters against synthetic trace rows."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
from graph_contract import CODES

from scripts.lib.dispatch_counters import REASONS, count_reasons


def line(code: str, event: str, ts: str = "2026-10-05T10:00:00+00:00") -> str:
    """One trace JSON line."""
    return json.dumps({"event_id": event, "ts": ts, "reason_code": code}) + "\n"


class DispatchCounterTests(unittest.TestCase):
    """Counts come from recovery-trace rows, are deduped per event and ignore everything else."""

    def test_every_contract_code_is_counted(self) -> None:
        """The counter's vocabulary is the contract's closed codes plus the allow row."""
        self.assertEqual(set(REASONS), {*CODES, "dispatch_authorized", "dispatch_check_off"})

    def test_counts_each_code_once_per_event(self) -> None:
        """A shared event id counts once; torn lines, unknown codes and rows before --since are ignored."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.assertEqual(set(count_reasons(root)), set(REASONS))
            (root / "p/S1").mkdir(parents=True)
            (root / "p/S1/recovery-trace.jsonl").write_text(
                line("dispatch_replayed", "a")
                + line("role_mismatch", "b") * 3
                + line("dispatch_authorized", "c")
                + "{torn\n"
                + line("other", "d")
                + line("dispatch_replayed", "old", ts="2026-01-01T00:00:00+00:00")
            )
            counts = count_reasons(root)
            found = (counts["dispatch_replayed"], counts["role_mismatch"], counts["dispatch_authorized"])
            self.assertEqual(found, (2, 1, 1))
            self.assertEqual(count_reasons(root, "2026-06-01")["dispatch_replayed"], 1)

    def test_foreign_owner_cli_refusal_is_counted_once(self) -> None:
        """Count the real owner refusal once without merging it into the envelope-refusal bucket."""
        repo = Path(__file__).resolve().parents[2]
        graph = repo / "packages/codex/skills/agentic-loop/scripts/graph.py"
        with tempfile.TemporaryDirectory() as name:
            scratch = Path(name)
            root = scratch / "loops"
            state = root / "project/counter-owner/progress.json"
            prompt = scratch / "prompt.txt"
            prompt.write_text("Measure an inert refusal in a disposable loop.", encoding="utf-8")
            env = {
                **os.environ,
                "HOME": str(scratch / "home"),
                "CLAUDE_AGENTIC_LOOP_DIR": str(root),
                "CODERAILS_AGENTIC_LOOP_DIR": str(root),
                "PYTHONDONTWRITEBYTECODE": "1",
            }

            def run(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-B", str(script), *arguments],
                    cwd=repo,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )

            for command, extra in (
                ("start", ["--prompt-file", str(prompt)]),
                ("instantiate", ["--profile", "full"]),
            ):
                created = run(graph, command, str(state), "--session", "counter-owner", "--loop-id", "counter", *extra)
                self.assertEqual(created.returncode, 0, created.stderr)
            before = state.read_bytes()
            refused = run(
                graph,
                "authorize-dispatch",
                str(state),
                "--session",
                "foreign-caller",
                "--dispatch-id",
                "absent-dispatch",
                "--message-file",
                str(scratch / "absent-message.txt"),
                "--task-name",
                "unused-task",
            )
            self.assertEqual(refused.returncode, 1, refused.stdout)
            self.assertIn("session does not own this loop", refused.stderr)
            self.assertEqual(state.read_bytes(), before)
            trace = state.with_name("recovery-trace.jsonl")
            rows = trace.read_text(encoding="utf-8").splitlines()
            owner_rows = [row for row in rows if json.loads(row).get("reason_code") == "dispatch_foreign_owner"]
            self.assertEqual(len(owner_rows), 1)
            with trace.open("a", encoding="utf-8") as stream:
                stream.write(owner_rows[0] + "\n")
            measured = run(repo / "scripts/lib/dispatch_counters.py")
            self.assertEqual(measured.returncode, 0, measured.stderr)
            counts = json.loads(measured.stdout)
            self.assertEqual(counts.get("dispatch_foreign_owner", 0), 1)
            self.assertEqual(counts["dispatch_foreign"], 0)


if __name__ == "__main__":
    unittest.main()
