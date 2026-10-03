"""Verify the graph-alignment measurement script against synthetic fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "measure_graph_alignment.py"
SECRET = "SECRET-PROMPT-CONTENT"
STUB = "import json\nprint(json.dumps({'hookSpecificOutput': {'additionalContext': 'x' * %d}}))\n"


def write(path: Path, text: str) -> None:
    """Create parents and write a UTF-8 file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def hooks_json(**events: int) -> str:
    """Build a hooks.json with N command hooks per event, split over two matcher groups when N > 1."""
    body = {
        name: [{"hooks": [{"type": "command", "command": f"h{i}"} for i in range(count)]}]
        for name, count in events.items()
    }
    return json.dumps({"hooks": body})


class MeasureTests(unittest.TestCase):
    """Run the CLI end to end with an isolated HOME, log redirects and repo root."""

    def setUp(self) -> None:
        """Create a synthetic repo root, an isolated home, and an environment pointing at them."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root, self.home = base / "repo", base / "home"
        self.home.mkdir()
        self.claude_log, self.codex_log = base / "claude.log", base / "codex.log"
        write(self.root / "hooks/hooks.json", hooks_json(SessionStart=2, Stop=3))
        write(self.root / "packages/codex/hooks/hooks.json", hooks_json(SessionStart=1, PreToolUse=4))
        write(self.root / "hooks/scripts/inject_bootstrap.py", STUB % 120)
        write(self.root / "packages/codex/hooks/scripts/inject_bootstrap.py", STUB % 30)
        write(self.root / "skills/using-coderails/SKILL.md", "s" * 50)
        self.env = {k: v for k, v in os.environ.items() if "AGENTIC_LOOP" not in k and k != "PLUGIN_DATA"}
        self.env.update(HOME=str(self.home), CLAUDE_DISCIPLINE_LOG=str(self.claude_log))
        self.env["CODERAILS_DISCIPLINE_LOG"] = str(self.codex_log)

    def run_cli(self, root: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Invoke the script as a subprocess against the fixture root."""
        command = [sys.executable, str(SCRIPT), "--root", str(root or self.root), "--json"]
        return subprocess.run(command, capture_output=True, text=True, env=self.env, check=False)

    def measure(self) -> dict[str, Any]:
        """Run successfully and return the parsed JSON object."""
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed: dict[str, Any] = json.loads(result.stdout)
        return parsed

    def progress(self, name: str, state: dict[str, Any]) -> None:
        """Write a loop progress.json under the default state root."""
        write(self.home / ".coderails/agentic-loop/slug" / name / "progress.json", json.dumps(state))

    def test_hook_counts_per_event_for_both_providers(self) -> None:
        """Hook commands are counted per event type with a total."""
        counts = self.measure()["hook_counts"]
        self.assertEqual(counts["claude"], {"SessionStart": 2, "Stop": 3, "total": 5})
        self.assertEqual(counts["codex"], {"SessionStart": 1, "PreToolUse": 4, "total": 5})

    def test_absent_codex_hooks_is_empty_not_error(self) -> None:
        """A repo without the Codex registration yields an empty codex entry."""
        (self.root / "packages/codex/hooks/hooks.json").unlink()
        self.assertEqual(self.measure()["hook_counts"]["codex"], {})

    def test_bootstrap_bytes_measure_injected_context(self) -> None:
        """Injected bytes come from the hook's additionalContext; skill bytes from the skill file."""
        boot = self.measure()["bootstrap_bytes"]
        self.assertEqual(boot["claude"]["injected_bytes"], 120)
        self.assertEqual(boot["claude"]["skill_bytes"], 50)
        self.assertEqual(boot["codex"]["injected_bytes"], 30)

    def test_telemetry_counts_blocked_would_block_warned(self) -> None:
        """Per-gate totals and flags are parsed; lines without a hook= field are ignored."""
        write(
            self.claude_log,
            "2026-01-01T00:00:00+00:00 hook=a event=Stop blocked=1\n"
            "2026-01-01T00:00:01+00:00 hook=a event=Stop blocked=0\n"
            "2026-01-01T00:00:02+00:00 hook=b would_block=1 warned=1 blocked=0\n"
            "2026-01-01T00:00:03+00:00 hook=a blocked=10\n"
            "garbage line without field\n",
        )
        claude = self.measure()["gate_blocks"]["claude"]
        self.assertEqual(
            claude["gates"]["a"], {"total": 3, "decisions": 2, "blocked": 1, "would_block": 0, "warned": 0}
        )
        self.assertEqual(
            claude["gates"]["b"], {"total": 1, "decisions": 1, "blocked": 0, "would_block": 1, "warned": 1}
        )
        self.assertEqual(claude["lines"], 4)
        self.assertEqual(
            (claude["first_timestamp"], claude["last_timestamp"]),
            ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:03+00:00"),
        )

    def test_missing_and_empty_logs_yield_zeros(self) -> None:
        """A missing Claude log and an empty Codex log both give zero lines, no error."""
        write(self.codex_log, "")
        gates = self.measure()["gate_blocks"]
        for provider in ("claude", "codex"):
            self.assertEqual((gates[provider]["lines"], gates[provider]["gates"]), (0, {}))

    def test_divergence_classification(self) -> None:
        """Units all terminal vs graph incomplete (or reverse) diverges; agreement and one-sided loops do not."""
        done, pending = {"status": "done"}, {"status": "pending"}
        self.progress("agree", {"work_units": {"u": done}, "graph": {"nodes": {"n": done}}})
        self.progress("units_done_graph_open", {"work_units": {"u": done}, "graph": {"nodes": {"n": pending}}})
        self.progress("graph_done_units_open", {"work_units": {"u": pending}, "graph": {"nodes": {"n": done}}})
        self.progress(
            "dropped_ok", {"work_units": {"u": {"status": "dropped"}}, "graph": {"nodes": {"n": {"status": "skipped"}}}}
        )
        self.progress(
            "freetext_done",
            {"work_units": {"u": {"status": "done (abc123); 5 tests"}}, "graph": {"nodes": {"n": done}}},
        )
        self.progress("graph_only", {"graph": {"nodes": {"n": pending}}})
        self.progress("legacy_list", {"work_units": [1, 2]})
        self.progress("broken", {})
        (self.home / ".coderails/agentic-loop/slug/broken/progress.json").write_text("{not json")
        scan = self.measure()["graph_vs_work_units"]
        self.assertEqual(
            {
                k: scan[k]
                for k in ("loops", "with_work_units", "with_graph_nodes", "with_both", "divergent", "divergent_lenient")
            },
            {
                "loops": 8,
                "with_work_units": 6,
                "with_graph_nodes": 6,
                "with_both": 5,
                "divergent": 3,
                "divergent_lenient": 2,
            },
        )

    def test_recovery_counters(self) -> None:
        """Recoveries, refused spawns and retries-by-cause come from state and the advisory trace, counts only."""
        node: dict[str, Any] = {
            "retry": {"attempts": 1, "max": 2},
            "respawn": {"generation": 2},
            "evidence": [{"kind": "worker", "outcome": "launch_refused"}, {"kind": "worker", "outcome": "stale"}, "x"],
        }
        self.progress("a", {"graph": {"nodes": {"n": node, "m": {"retry": {"attempts": 0}, "respawn": {}}}}})
        trace = self.home / ".coderails/agentic-loop/slug/a/recovery-trace.jsonl"
        rows = [("recovered", "recovered"), ("recovered", "recovered"), ("refused", "foreign_session")]
        write(trace, "".join(json.dumps({"outcome": o, "reason_code": c}) + "\n" for o, c in rows) + "not json\n")
        self.assertEqual(
            self.measure()["recovery"],
            {
                "recoveries": 2,
                "refused_spawns": 1,
                "retries_by_cause": {"failed": 1, "stale_recovery": 2},
                "trace_rows_by_reason_code": {"foreign_session": 1, "recovered": 2},
            },
        )

    def test_nonexistent_root_fails_closed(self) -> None:
        """A missing root exits non-zero with a stderr message and no stdout."""
        result = self.run_cli(self.root / "nope")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("not a directory", result.stderr)

    def test_no_content_leakage(self) -> None:
        """Secrets in state files and log lines never reach stdout or stderr."""
        self.progress(
            "leaky",
            {
                "work_units": {"u": {"status": "done", "note": SECRET}},
                "graph": {"nodes": {"n": {"status": "done", "evidence": [SECRET]}}},
            },
        )
        write(self.claude_log, f"2026-01-01T00:00:00+00:00 hook=a blocked=1 reason={SECRET}\n")
        write(self.root / "skills/using-coderails/SKILL.md", SECRET)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(SECRET, result.stdout + result.stderr)

    def test_duplication_reports_copies(self) -> None:
        """graph_semantics copies are line-counted and compared by content."""
        write(self.root / "packages/graph-semantics/graph_semantics.py", "a\nb\n")
        write(self.root / "skills/agentic-loop/scripts/graph_semantics.py", "a\nb\n")
        write(self.root / "packages/codex/skills/agentic-loop/scripts/graph_semantics.py", "a\nb\nc\n")
        dup = self.measure()["duplication"]
        self.assertEqual(sorted(dup["graph_semantics_lines"].values()), [2, 2, 3])
        self.assertEqual(dup["graph_semantics_distinct_contents"], 2)


if __name__ == "__main__":
    unittest.main()
