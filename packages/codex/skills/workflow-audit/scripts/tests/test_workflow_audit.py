#!/usr/bin/env python3
"""Behavioural coverage for the native workflow-audit Python entry points."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent
SCAN = SCRIPTS / "scan_transcripts.py"
CLUSTER = SCRIPTS / "cluster_ngrams.py"
WRITE = SCRIPTS / "write_queue_entry.py"


def run(
    script: Path,
    *args: str,
    input_text: str = "",
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one workflow-audit entry point with controlled session variables."""
    process_env = dict(env or os.environ)
    process_env.pop("CODEX_SESSION_ID", None)
    process_env.pop("CODEX_THREAD_ID", None)
    if env:
        process_env.update({key: value for key, value in env.items() if key in {"CODEX_SESSION_ID", "CODEX_THREAD_ID"}})
    return subprocess.run(
        [sys.executable, script, *args],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        env=process_env,
    )


def session(session_id: str, project: str, events: list[dict[str, object]]) -> str:
    """Build a minimal native transcript with one root-session metadata record."""
    records: list[dict[str, object]] = [
        {
            "type": "session_meta",
            "timestamp": "2026-07-06T10:00:00Z",
            "payload": {
                "id": session_id,
                "session_id": session_id,
                "cwd": f"/work/{project}",
                "parent_thread_id": None,
            },
        }
    ]
    records.extend(
        {"type": "event_msg", "timestamp": "2026-07-06T10:00:01Z", "payload": {"type": "item_completed", "item": event}}
        for event in events
    )
    return "\n".join(json.dumps(record) for record in records) + "\n"


class WorkflowAuditTests(unittest.TestCase):
    """Verify privacy, clustering, and protected queue-entry contracts."""

    def test_scan_preserves_only_whitelisted_event_data(self) -> None:
        """Scanner emits only its four intentionally whitelisted event shapes."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "2026/07/06/session.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                session(
                    "scan",
                    "project",
                    [
                        {"type": "CommandExecution", "command": ["zsh", "-lc", "git log --secret"]},
                        {"type": "FileChange", "changes": [{"path": "secret"}]},
                        {"type": "Extension", "kind": "web.search"},
                        {"type": "CollabAgentToolCall", "tool": "spawn_agent", "prompt": "secret"},
                    ],
                ),
                encoding="utf-8",
            )
            result = run(SCAN, "--project", "project", "--days", "36500", env={"WORKFLOW_AUDIT_ROOT": str(root)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("scanning file_count=1", result.stderr)
            self.assertNotIn("secret", result.stdout)
            self.assertEqual(
                json.loads(result.stdout)["events"],
                [
                    {"tool": "CommandExecution", "head": "git log"},
                    {"tool": "FileChange"},
                    {"tool": "Extension", "head": "web.search"},
                    {"tool": "CollabAgentToolCall", "head": "spawn_agent"},
                ],
            )

    def test_scan_reports_corrupt_input_and_excludes_current_session(self) -> None:
        """Scanner warns on corrupt JSONL and never mines the current session."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "session.jsonl"
            path.write_text(session("current", "project", []) + "{broken\n", encoding="utf-8")
            result = run(SCAN, "--days", "36500", env={"WORKFLOW_AUDIT_ROOT": str(root), "CODEX_SESSION_ID": "current"})
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertIn("jq_parse_error:", result.stderr)
            self.assertIn("skipped_own_session:", result.stderr)

    def test_cluster_counts_occurrences_but_requires_distinct_sessions(self) -> None:
        """Clusters require the configured number of distinct source sessions."""
        rows = "\n".join(
            json.dumps(
                {
                    "session_id": session_id,
                    "events": [{"tool": "Bash", "head": "git log"}, {"tool": "Bash", "head": "git push"}],
                }
            )
            for session_id in ("a", "b", "c")
        )
        result = run(CLUSTER, "--min-sessions", "3", input_text=rows + "\n{broken\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("jq_parse_error:4", result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["scanned_sessions"], 3)
        self.assertEqual(
            output["clusters"],
            [{"ngram": ["Bash:git log", "Bash:git push"], "n": 2, "count": 3, "sessions": ["a", "b", "c"]}],
        )

    def test_scan_to_cluster_pipeline(self) -> None:
        """Scanner output remains directly consumable by the cluster entry point."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for session_id in ("a", "b", "c"):
                path = root / f"{session_id}.jsonl"
                path.write_text(
                    session(
                        session_id,
                        session_id,
                        [
                            {"type": "CommandExecution", "command": ["zsh", "-lc", "git log --oneline"]},
                            {"type": "CommandExecution", "command": ["zsh", "-lc", "git push origin"]},
                            {"type": "CollabAgentToolCall", "tool": "spawn_agent"},
                        ],
                    ),
                    encoding="utf-8",
                )
            scan = run(SCAN, "--days", "36500", env={"WORKFLOW_AUDIT_ROOT": str(root)})
            cluster = run(CLUSTER, "--min-sessions", "3", input_text=scan.stdout)
            self.assertEqual(cluster.returncode, 0, cluster.stderr)
            self.assertTrue(any(item["n"] == 3 for item in json.loads(cluster.stdout)["clusters"]))

    def test_queue_writer_whitelists_and_protects_output(self) -> None:
        """Queue writer drops non-contract fields and creates owner-only files."""
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "queue"
            verdict = {
                "verdict": "propose",
                "cluster_ngram": ["Bash:git log"],
                "task_summary": "summary",
                "proposed_name": "name",
                "proposed_description": "description",
                "raw": "never-copy",
            }
            result = run(
                WRITE, "--queue-dir", str(queue), "--count", "3", "--sessions", '["a"]', input_text=json.dumps(verdict)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            digest = result.stdout.strip()
            entry = json.loads((queue / f"{digest}.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(entry["toolInput"]),
                {"cluster_ngram", "count", "sessions", "task_summary", "proposed_name", "proposed_description"},
            )
            self.assertNotIn("never-copy", json.dumps(entry))
            self.assertEqual(stat.S_IMODE(queue.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((queue / f"{digest}.json").stat().st_mode), 0o600)

    def test_queue_writer_reject_and_malformed_input_do_not_write(self) -> None:
        """Reject and malformed verdicts leave no queue entry behind."""
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "queue"
            reject = run(WRITE, "--queue-dir", str(queue), input_text='{"verdict":"reject"}')
            malformed = run(WRITE, "--queue-dir", str(queue), input_text="{")
            self.assertEqual(reject.returncode, 0)
            self.assertEqual(reject.stdout, "")
            self.assertFalse(queue.exists())
            self.assertEqual(malformed.returncode, 1)
            self.assertIn("jq_parse_error:stdin", malformed.stderr)


if __name__ == "__main__":
    unittest.main()
