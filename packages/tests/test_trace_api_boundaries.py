"""Keep standalone hook traces and generic proof events on their public emission paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class TraceApiBoundaryTests(unittest.TestCase):
    """Use separate native processes and private output paths without running proofs."""

    def environment(self, home: Path) -> dict[str, str]:
        """Keep each subprocess outside user configuration and Python package paths."""
        allowed = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "TMPDIR"}}
        return {
            **allowed,
            "HOME": str(home),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "CLAUDE_AGENTIC_LOOP_DIR": str(home / "loops"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(home / "loops"),
            "CODERAILS_HOOK_TELEMETRY_DIR": str(home / "telemetry"),
        }

    def test_standalone_context_hooks_keep_detailed_traces(self) -> None:
        """Both standalone providers retain the context event as well as typed hook telemetry."""
        for provider in (ROOT, ROOT / "packages/codex"):
            for hook, command in (("inject_context", "context_route"), ("inject_bootstrap", "context_manifest")):
                with self.subTest(provider=provider, hook=hook), tempfile.TemporaryDirectory() as scratch:
                    home = Path(scratch)
                    process = subprocess.run(
                        [sys.executable, str(provider / "hooks/scripts" / f"{hook}.py")],
                        input="{",
                        env=self.environment(home),
                        cwd=home,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=10,
                    )
                    self.assertEqual(process.returncode, 0, process.stderr)
                    self.assertIn("hookSpecificOutput", json.loads(process.stdout))
                    path = home / "loops/_unattributed/trace.jsonl"
                    self.assertTrue(path.is_file(), "standalone hook lost its detailed context trace")
                    rows = [json.loads(line) for line in path.read_text().splitlines()]
                    self.assertEqual([(row["command"], row["outcome"]) for row in rows], [(command, "fail_open")])
                    self.assertEqual(rows[0]["decision_record"]["hook"], command)
                    self.assertEqual(rows[0]["decision_record"]["reason_code"], rows[0]["reason_code"])
                    telemetry = [
                        json.loads(line) for line in (home / "telemetry/hook_telemetry.jsonl").read_text().splitlines()
                    ]
                    self.assertEqual(telemetry[-1]["decision_record"]["hook"], hook)
                    self.assertEqual(telemetry[-1]["decision_record"]["decision"], "ok")

    def test_generic_proof_emitter_keeps_retained_event_vocabulary(self) -> None:
        """Call only the real proof trace emitter, including successful events with empty reasons."""
        code = (
            "import json,sys\n"
            "sys.path.insert(0,sys.argv[1])\n"
            "from scripts.lib import proof_results as proof\n"
            "events=[('proof.freeze','frozen',''),('proof.freeze','disposition',''),('proof.run','satisfied','')]\n"
            "events += [('proof.run',verdict,reason) for verdict,reason in proof.VERDICT_REASON.items()]\n"
            "for command,outcome,reason in events: proof.trace(command,outcome,reason,'session','loop')\n"
            "print(json.dumps(events))\n"
        )
        for provider in (ROOT, ROOT / "packages/codex"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as scratch:
                home = Path(scratch)
                process = subprocess.run(
                    [sys.executable, "-c", code, str(provider)],
                    env=self.environment(home),
                    cwd=home,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                expected = json.loads(process.stdout)
                path = home / "loops/session/trace.jsonl"
                self.assertTrue(path.is_file(), "generic proof emitter lost every trace")
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual([[row["command"], row["outcome"], row["reason_code"]] for row in rows], expected)
                for row in rows:
                    self.assertNotIn("decision_record", row, "a generic proof event is not a typed hook decision")


if __name__ == "__main__":
    unittest.main()
