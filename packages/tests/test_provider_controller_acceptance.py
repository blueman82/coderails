"""Scripted live schema-v3 run through both providers' real CLIs, then a compaction-resume check.

Set CODERAILS_ACCEPTANCE_TRANSCRIPT=<file> to save the command-by-command transcript.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider

LOOP = "fixture-loop"  # the fixture's frozen evals.json is bound to this loop id


class AcceptanceTests(unittest.TestCase):
    """start, add-unit x2 with a dependency, plan, waves, record-unit, complete, verify-completion."""

    def setUp(self) -> None:
        """Isolated HOME and state per provider."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]
        self.lines: list[str] = []

    def run_cli(self, provider: Provider, command: str, *arguments: str) -> dict[str, Any]:
        """Run one real CLI command, log it, require success and return its JSON."""
        result = provider.call(command, *arguments)
        self.lines.append(
            f"[{provider.name}] graph.py {command} {' '.join(arguments)[:90]} -> exit {result.returncode}"
        )
        self.lines.append(f"    {result.stdout.strip()[:300]}{result.stderr.strip()[:300]}")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)  # type: ignore[no-any-return]

    def completion_args(self, provider: Provider) -> list[str]:
        """Each provider's native completion options."""
        args = ["--session", provider.session]
        if provider.name == "codex":
            for name in ("evals", "proof", "retro"):
                args += ["--" + name, str(provider.path.with_name(name + ".json"))]
            args += ["--transcript", str(provider.parent)]
        return args

    def test_full_run_and_compaction_resume(self) -> None:
        """The whole controller lifecycle, with state re-read from disk keeping owner, wave and evidence identity."""
        for p in self.providers:
            with self.subTest(provider=p.name):
                p.path.unlink()
                prompt = p.home / "prompt.txt"
                prompt.write_text("Authorised outcome, verbatim.\n")
                ident = ("--session", p.session, "--loop-id", LOOP)
                self.run_cli(p, "start", *ident, "--prompt-file", str(prompt))
                self.run_cli(p, "add-unit", *ident, "--unit", "1", "--join")
                self.run_cli(p, "add-unit", *ident, "--unit", "2", "--depends-on", "1", "--join")
                if p.name == "claude":
                    planned = p.call("plan")
                    self.assertEqual(planned.returncode, 0, planned.stderr)
                    self.assertEqual([item["node_id"] for item in json.loads(planned.stdout)], ["U3[1]"])
                self.assertEqual(self.run_cli(p, "inspect")["ready"], ["U3[1]"])

                wave1 = self.run_cli(p, "begin-wave")
                self.assertEqual(wave1["nodes"], ["U3[1]"])
                before = self.run_cli(p, "inspect")
                # compaction: nothing in memory survives; a fresh process re-reads the file
                resumed = self.run_cli(p, "inspect")
                self.assertEqual((resumed["session_id"], resumed["loop_id"]), (p.session, LOOP))
                self.assertEqual(resumed["active_wave"], before["active_wave"])
                self.assertEqual(self.run_cli(p, "summarize")["phase"], "waiting for worker")

                self.run_cli(p, "record-wave", json.dumps(p.launch()))
                evidence = p.read()["graph"]["nodes"]["U3[1]"]["evidence"]
                self.assertTrue(evidence)
                wave2 = self.run_cli(p, "begin-wave")
                self.assertEqual(wave2["nodes"], ["U3[2]"])
                recorded = self.run_cli(p, "record-wave", json.dumps(p.launch()))
                self.assertEqual(recorded["released_joins"], ["J12-all-units"])
                self.assertEqual(p.read()["graph"]["nodes"]["U3[1]"]["evidence"], evidence)
                for unit in ("1", "2"):
                    self.run_cli(
                        p,
                        "record-unit",
                        "--session",
                        p.session,
                        "--unit",
                        unit,
                        "--status",
                        "done",
                        "--evidence",
                        "checked",
                    )
                p.artifacts()
                self.run_cli(p, "complete", *self.completion_args(p))
                self.run_cli(p, "verify-completion", *self.completion_args(p))

                final = p.read()  # second compaction: re-read the finished file
                self.assertEqual(
                    (final["session_id"], final["loop_id"], final["status"]), (p.session, LOOP, "complete")
                )
                self.assertEqual(final["graph"]["nodes"]["U3[1]"]["evidence"], evidence)
                self.assertEqual(
                    final["work_units"],
                    {"1": {"status": "done", "evidence": "checked"}, "2": {"status": "done", "evidence": "checked"}},
                )
        target = os.environ.get("CODERAILS_ACCEPTANCE_TRANSCRIPT")
        if target:
            Path(target).write_text("\n".join(self.lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
