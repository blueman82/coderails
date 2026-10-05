"""The controller runs frozen proof commands verbatim, records chained results, and the gates read only those."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.loop_proofs import validate_proofs
from scripts.lib import proof_results as pr

REPO = Path(__file__).resolve().parents[2]
PROOF = REPO / "scripts/lib/proof.py"
SESSION, LOOP = "sess", "loop"


class ProofRunTests(unittest.TestCase):
    """Rows are written by proof.py; validate_proofs releases or blocks from them alone."""

    def setUp(self) -> None:
        """Create a state dir with progress.json."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.dir = Path(temporary.name)
        (self.dir / "progress.json").write_text(json.dumps({"session_id": SESSION, "loop_id": LOOP}))
        self.state: dict[str, Any] = {"session_id": SESSION, "loop_id": LOOP}
        self.proof = self.dir / "proof.json"
        self.results = self.dir / pr.RESULTS_NAME

    def doc(self, *proofs: dict[str, Any], **extra: list[dict[str, Any]]) -> None:
        """Write a schema-2 proof.json."""
        body = {"schema_version": 2, "session_id": SESSION, "loop_id": LOOP, "proofs": list(proofs)} | extra
        self.proof.write_text(json.dumps(body))

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run proof.py from the state dir."""
        return subprocess.run(
            [sys.executable, str(PROOF), *args], cwd=self.dir, capture_output=True, text=True, check=False
        )

    def freeze_run(self, *flags: str) -> list[dict[str, Any]]:
        """Freeze, run everything, and return the run rows."""
        self.assertEqual(self.cli("freeze", str(self.dir)).returncode, 0)
        self.cli("run", str(self.dir), *flags)
        return [r for r in pr.read_rows(self.results) if r["kind"] == "run"]

    def gate(self) -> str:
        """Run the Claude gate with an empty transcript."""
        return validate_proofs(self.proof, self.state, "")

    def blocked(self, pattern: str) -> None:
        """Assert the gate blocks with a message matching pattern."""
        with self.assertRaisesRegex(ValueError, pattern):
            self.gate()

    def test_run_row_hash_and_gate_release_without_transcript(self) -> None:
        """(a)(7) The run row hashes the stripped cmd; a satisfied row releases the gate with no transcript."""
        cmd = 'echo "$(printf ok)"\n'
        self.doc({"id": "P1", "cmd": cmd, "expect": {"exit_code": 0, "stdout_contains": ["ok"]}})
        self.blocked(r"P1\(proof_stale_cmd\)")
        (row,) = self.freeze_run("--all")
        self.assertEqual(row["cmd_sha256"], pr.sha(cmd.strip()))
        self.assertNotEqual(row["cmd_sha256"], pr.sha(cmd))
        self.assertEqual((row["exit_code"], row["verdict"], row["expect_matched"]), (0, "satisfied", True))
        self.assertEqual(self.gate(), "")

    def test_verbatim_execution(self) -> None:
        """(b) Nested quotes and $() run exactly as written: exit 3, verdict failed, cmd hash unchanged."""
        cmd = 'bash -c \'printf "%s\\n" "$0 x"; exit 3\''
        self.doc({"id": "P1", "cmd": cmd, "expect": {"exit_code": 0}})
        (row,) = self.freeze_run()
        self.assertEqual((row["exit_code"], row["verdict"]), (3, "failed"))
        self.assertEqual(row["cmd_sha256"], pr.sha(cmd))
        self.assertIn("bash x", row["excerpt"])
        self.blocked(r"P1\(proof_failed\)")

    def test_expect_is_honoured(self) -> None:
        """(c) Missing required stdout or present forbidden stdout is expect_mismatch and the gate names the id."""
        for expect in ({"stdout_contains": ["absent"]}, {"stdout_not_contains": ["hello"]}):
            self.doc({"id": "P9", "cmd": "echo hello", "expect": {"exit_code": 0} | expect})
            (row,) = self.freeze_run()
            self.assertEqual(row["verdict"], "expect_mismatch")
            self.blocked(r"P9\(proof_expect_mismatch\)")
            self.results.unlink()

    def test_expected_nonzero_exit_is_satisfied(self) -> None:
        """A frozen exit_code of 3 is satisfied by exit 3."""
        self.doc({"id": "P1", "cmd": "exit 3", "expect": {"exit_code": 3}})
        self.freeze_run()
        self.assertEqual(self.gate(), "")

    def test_status_field_never_counts(self) -> None:
        """(d) An orchestrator-written status of pass with no run row blocks as proof_unexecuted."""
        self.doc({"id": "P1", "cmd": "true", "status": "pass", "expect": {"exit_code": 0}})
        self.assertEqual(self.cli("freeze", str(self.dir)).returncode, 0)
        self.blocked(r"P1\(proof_unexecuted\)")

    def test_stale_freeze_wrong_hash_and_broken_chain(self) -> None:
        """(e)(4)(5) Editing after freeze, a forged cmd hash, or a deleted middle row all block."""
        self.doc({"id": "P1", "cmd": "true", "expect": {"exit_code": 0}}, withdrawn_proofs=[])
        self.freeze_run()
        self.assertEqual(self.gate(), "")
        good = self.proof.read_text()
        self.doc({"id": "P1", "cmd": "false", "expect": {"exit_code": 0}})
        self.blocked(r"P1\(proof_stale_cmd\)")
        self.proof.write_text(good)
        rows = pr.read_rows(self.results)
        pr.append(
            self.results,
            kind="run",
            proof_id="P1",
            cmd_sha256=pr.sha("other"),
            session_id=SESSION,
            loop_id=LOOP,
            proof_json_sha256=rows[0]["proof_json_sha256"],
            verdict="satisfied",
        )
        self.blocked(r"P1\(proof_stale_cmd\)")
        lines = self.results.read_text().splitlines()
        self.results.write_text("\n".join([lines[0], lines[2]]) + "\n")
        self.blocked(r"P1\(proof_chain_broken\)")

    def test_disposition_forms(self) -> None:
        """(f) Bare none is rejected; none: reason, the typed dict, and the CLI-recorded row pass."""
        for rejected in ("none", "none:", "none:  ", "expected", "", None, {"kind": "none", "reason": "x"}):
            self.state["proof_disposition"] = rejected
            self.blocked("disposition")
        for accepted in ("none: no executable surface", {"kind": "none", "reason_code": "docs_only", "reason": "docs"}):
            self.state["proof_disposition"] = accepted
            self.assertEqual(self.gate(), "")
        self.state.pop("proof_disposition")
        self.blocked("disposition")
        self.assertEqual(
            self.cli(
                "disposition", str(self.dir), "--none", "--reason-code", "docs_only", "--reason", "docs only"
            ).returncode,
            0,
        )
        self.assertEqual(self.gate(), "")
        self.assertEqual(
            self.cli("disposition", str(self.dir), "--none", "--reason-code", " ", "--reason", "x").returncode, 2
        )

    def test_destructive_cmd_is_refused_and_never_run(self) -> None:
        """(g)(6) A destructive frozen cmd is recorded as refused and does not execute."""
        victim = self.dir / "victim"
        victim.mkdir()
        self.doc({"id": "P1", "cmd": f"rm -rf {victim}", "expect": {"exit_code": 0}})
        (row,) = self.freeze_run()
        self.assertEqual((row["verdict"], row["exit_code"]), ("refused", None))
        self.assertTrue(victim.is_dir())
        self.blocked(r"P1\(proof_cmd_destructive\)")

    def test_withdrawn_proofs_need_an_observed_failure_and_reason(self) -> None:
        """(h) A withdrawn proof passes only with a failed/timeout row and a reason; a satisfied row does not."""
        ok = {"id": "P1", "cmd": "true", "expect": {"exit_code": 0}}
        bad = {"id": "W1", "cmd": "exit 1", "expect": {"exit_code": 0}, "withdrawn_reason": "wrong assumption"}
        self.doc(ok, withdrawn_proofs=[bad])
        self.freeze_run()
        self.assertEqual(self.gate(), "Withdrawn proofs: W1: wrong assumption")
        self.doc(ok, withdrawn_proofs=[bad | {"cmd": "true"}])
        self.results.unlink()
        self.freeze_run()
        self.blocked(r"W1\(proof_withdrawn_unobserved\)")
        self.doc(ok, withdrawn_proofs=[bad | {"withdrawn_reason": " "}])
        self.results.unlink()
        self.freeze_run()
        self.blocked(r"W1\(proof_withdrawn_unobserved\)")

    def test_timeout_is_enforced(self) -> None:
        """(i) A sleeping cmd past timeout_s records verdict timeout."""
        self.doc({"id": "P1", "cmd": "sleep 30", "timeout_s": 0.5, "expect": {"exit_code": 0}})
        (row,) = self.freeze_run()
        self.assertEqual((row["verdict"], row["exit_code"]), ("timeout", None))
        self.blocked(r"P1\(proof_failed\)")

    def test_legacy_schema_one_runs_exit_zero_only_and_is_flagged(self) -> None:
        """A schema 1 proof with prose expect runs, checks exit 0 only, and is flagged expect_unstructured."""
        self.proof.write_text(
            json.dumps({"schema_version": 1, "proofs": [{"id": "P1", "cmd": "echo hi", "expect": "prints hi"}]})
        )
        (row,) = self.freeze_run()
        self.assertEqual(row["verdict"], "satisfied")
        self.assertTrue(row["excerpt"].startswith("[expect_unstructured]"))

    def test_freeze_rejects_invalid_documents(self) -> None:
        """Duplicate ids, blank cmds, unstructured v2 expect and bad timeouts are refused at freeze."""
        bad: list[dict[str, Any]] = [
            {"schema_version": 2, "proofs": [{"id": "A", "cmd": "true", "expect": {}}] * 2},
            {"schema_version": 2, "proofs": [{"id": "A", "cmd": " ", "expect": {}}]},
            {"schema_version": 2, "proofs": [{"id": "A", "cmd": "true", "expect": "prose"}]},
            {"schema_version": 2, "proofs": [{"id": "A", "cmd": "true", "expect": {}, "timeout_s": 0}]},
            {"schema_version": 3, "proofs": [{"id": "A", "cmd": "true"}]},
        ]
        for document in bad:
            self.proof.write_text(json.dumps(document))
            self.assertEqual(self.cli("freeze", str(self.dir)).returncode, 2, document)
        self.assertFalse(self.results.exists())

    def test_foreign_session_rows_do_not_count(self) -> None:
        """A run row recorded under another session or loop never satisfies this loop's proof."""
        self.doc({"id": "P1", "cmd": "true", "expect": {"exit_code": 0}})
        self.freeze_run()
        self.assertEqual(self.gate(), "")
        self.state["loop_id"] = "other"
        self.blocked(r"P1\((proof_stale_cmd|proof_unexecuted)\)")

    def test_every_reason_code_is_in_the_runbook(self) -> None:
        """Each proof reason code is named in docs/RUNBOOK.md."""
        runbook = (REPO / "docs/RUNBOOK.md").read_text()
        for code in pr.REASONS:
            self.assertIn(code, runbook)

    def test_mirror_size_and_no_transcript_mining(self) -> None:
        """(j) Codex copies are byte-identical, files stay under 400 lines, transcript mining is gone."""
        for name in ("proof_results.py", "proof.py"):
            source, mirror = REPO / "scripts/lib" / name, REPO / "packages/codex/scripts/lib" / name
            self.assertEqual(source.read_bytes(), mirror.read_bytes(), name)
            self.assertLess(len(source.read_text().splitlines()), 400, name)
        for relative in (
            "hooks/scripts/lib/loop_proofs.py",
            "packages/codex/skills/agentic-loop/scripts/graph_artifacts.py",
        ):
            text = (REPO / relative).read_text()
            for gone in ("proof_executions", "_validate_observed_proofs", "parse_exec_result", "tool_use"):
                self.assertNotIn(gone, text, relative)


if __name__ == "__main__":
    unittest.main()
