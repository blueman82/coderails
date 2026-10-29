"""Keep a frozen proof file intact while one checked replacement becomes active."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.loop_proofs import validate_proofs
from scripts.lib import handoff_derive, retro_check
from scripts.lib import proof_results as pr
from scripts.lib import proof_suite as suite

ROOT = Path(__file__).resolve().parents[2]
RUNNERS = (ROOT / "scripts/lib/proof.py", ROOT / "packages/codex/scripts/lib/proof.py")


class SupersessionTests(unittest.TestCase):
    """Exercise one replacement against synthetic or copied closure state."""

    def setUp(self) -> None:
        """Create a private graph copy, candidate, and author report."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        scratch = Path(temporary.name)
        self.state = scratch / "graph"
        self.state.mkdir()
        active = os.getenv("CODERAILS_PROOF_TEST_GRAPH")
        if active:
            source = Path(active)
            shutil.copyfile(source / "progress.json", self.state / "progress.json")
            shutil.copyfile(source / "proof.json", self.state / "proof.json")
            source_proof = json.loads((self.state / "proof.json").read_text())
            self.identity = {key: source_proof[key] for key in ("session_id", "loop_id")}
        else:
            self.identity = {"session_id": "session", "loop_id": "loop"}
            (self.state / "progress.json").write_text(json.dumps(self.identity))
            (self.state / "proof.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        **self.identity,
                        "proofs": [{"id": "OLD", "cmd": "true", "expect": {"exit_code": 0}}],
                    }
                )
            )
        self.original = (self.state / "proof.json").read_bytes()
        self.candidate = scratch / "candidate.json"
        self.candidate.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    **self.identity,
                    "amendments": [],
                    "proofs": [
                        {
                            "id": "NEW",
                            "cmd": "printf 'ready\\n'",
                            "status": "pending",
                            "expect": {"exit_code": 0, "stdout_contains": ["ready"]},
                        }
                    ],
                }
            )
        )
        self.evidence = scratch / "author-report.txt"
        self.evidence.write_text("Independent author report for this test.\n")

    def cli(self, runner: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run either provider's proof controller."""
        return subprocess.run(
            [sys.executable, str(runner), *arguments], cwd=ROOT, capture_output=True, text=True, check=False
        )

    def supersede(self, runner: Path) -> subprocess.CompletedProcess[str]:
        """Submit the test candidate with the original raw hash."""
        return self.cli(
            runner,
            "supersede",
            str(self.state),
            "--candidate",
            str(self.candidate),
            "--reason",
            "original commands use a retired path",
            "--original-sha256",
            hashlib.sha256(self.original).hexdigest(),
            "--author-evidence",
            str(self.evidence),
        )

    def active(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
        """Read the selected suite and its binding cutoff."""
        return suite.active_suite(self.state / "proof.json", self.identity)

    def gate(self) -> str:
        """Check the Claude completion proof boundary."""
        return validate_proofs(self.state / "proof.json", self.identity)

    def codex_gate(self) -> subprocess.CompletedProcess[str]:
        """Check the independent Codex proof boundary in its own process."""
        code = (
            "import json,sys; from pathlib import Path; "
            "sys.path.insert(0,sys.argv[1]); sys.path.insert(0,sys.argv[2]); import graph_artifacts; "
            "graph_artifacts._validate_proofs(json.loads(Path(sys.argv[3]).read_text()),Path(sys.argv[4]))"
        )
        return subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(ROOT / "packages/codex"),
                str(ROOT / "packages/codex/skills/agentic-loop/scripts"),
                str(self.state / "progress.json"),
                str(self.state / "proof.json"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_one_replacement_preserves_original_and_rejects_duplicate(self) -> None:
        """A replacement selects only its candidate and leaves original bytes untouched."""
        for runner in RUNNERS:
            with self.subTest(runner=runner):
                result = self.supersede(runner)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((self.state / "proof.json").read_bytes(), self.original)
                self.assertEqual(self.supersede(runner).returncode, 2)
                self.assertEqual(self.cli(runner, "freeze", str(self.state)).returncode, 0)
                status = self.cli(runner, "status", str(self.state))
                self.assertIn("NEW\tunexecuted", status.stdout)
                self.assertNotIn("OLD\t", status.stdout)
                (self.state / "proof_results.jsonl").unlink()
                shutil.rmtree(self.state / "proof_candidates")

    def test_supersede_ignores_git_from_inherited_path(self) -> None:
        """Both controllers must use trusted Git before they bind a replacement."""
        bin_dir = self.state.parent / "bin"
        bin_dir.mkdir()
        marker = self.state.parent / "git-canary"
        fake = bin_dir / "git"
        fake.write_text(f"#!/bin/sh\nprintf attacked > {marker}\nexit 92\n")
        fake.chmod(0o755)
        with patch.dict(os.environ, {"PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}):
            for runner in RUNNERS:
                with self.subTest(runner=runner):
                    result = self.supersede(runner)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertFalse(marker.exists())
                    (self.state / pr.RESULTS_NAME).unlink()
                    shutil.rmtree(self.state / "proof_candidates")

    def test_old_rows_cannot_satisfy_replacement_and_new_head_rows_can(self) -> None:
        """Old rows and stale-HEAD rows fail both provider gates."""
        candidate = json.loads(self.candidate.read_text())
        candidate["proofs"][0]["id"] = "OLD"
        self.candidate.write_text(json.dumps(candidate))
        digest = pr.doc_sha(candidate)
        results = self.state / pr.RESULTS_NAME
        pr.append(results, kind="freeze", proof_json_sha256=digest, **self.identity)
        pr.append(
            results,
            kind="run",
            proof_id="OLD",
            cmd_sha256=pr.sha(candidate["proofs"][0]["cmd"]),
            proof_json_sha256=digest,
            verdict="satisfied",
            cwd=str(ROOT),
            head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            **self.identity,
        )
        self.assertEqual(self.supersede(RUNNERS[0]).returncode, 0)
        with self.assertRaisesRegex(ValueError, "OLD\\(proof_stale_cmd\\)"):
            self.gate()
        self.assertNotEqual(self.codex_gate().returncode, 0)
        self.assertEqual(self.cli(RUNNERS[0], "freeze", str(self.state)).returncode, 0)
        pr.append(
            results,
            kind="run",
            proof_id="OLD",
            cmd_sha256=pr.sha(candidate["proofs"][0]["cmd"]),
            proof_json_sha256=digest,
            verdict="satisfied",
            cwd=str(ROOT),
            head_sha="0" * 40,
            **self.identity,
        )
        with self.assertRaisesRegex(ValueError, "proof_stale_head"):
            self.gate()
        self.assertEqual(self.cli(RUNNERS[0], "run", str(self.state), "--all").returncode, 0)
        self.assertEqual(self.gate(), "")
        self.assertEqual(self.codex_gate().returncode, 0)

    def test_retro_and_handoff_report_only_the_selected_proof_run(self) -> None:
        """A prior successful run cannot appear under a replacement suite."""
        original = json.loads((self.state / "proof.json").read_text())
        results = self.state / pr.RESULTS_NAME
        pr.append(results, kind="freeze", proof_json_sha256=pr.doc_sha(original), **self.identity)
        run = {
            "kind": "run",
            "cmd_sha256": pr.sha("true"),
            "verdict": "satisfied",
            "cwd": str(ROOT),
            "head_sha": "0" * 40,
            **self.identity,
        }
        pr.append(results, proof_id="OLD", proof_json_sha256=pr.doc_sha(original), **run)
        self.assertEqual(self.supersede(RUNNERS[0]).returncode, 0)
        self.assertEqual(retro_check.proof_summary(self.state, self.identity)["verdicts"], {})
        degraded: list[dict[str, str]] = []
        recorded, pending = handoff_derive.proof_lines(self.state, self.identity, degraded)
        self.assertEqual((recorded, pending, degraded), (["proof NEW: unexecuted"], ["proof NEW: unexecuted"], []))
        selected, _, _ = self.active()
        assert selected is not None
        pr.append(results, proof_id="NEW", proof_json_sha256=pr.doc_sha(selected), **run)
        self.assertEqual(retro_check.proof_summary(self.state, self.identity)["verdicts"], {})
        self.assertEqual(handoff_derive.proof_lines(self.state, self.identity, degraded)[0], ["proof NEW: unexecuted"])

    def test_tampered_original_candidate_evidence_and_chain_block(self) -> None:
        """Every bound file and the hash chain must retain its recorded bytes."""
        self.assertEqual(self.supersede(RUNNERS[0]).returncode, 0)
        replacement, rows, _ = self.active()
        assert replacement is not None
        self.assertEqual(replacement["proofs"][0]["id"], "NEW")
        assert isinstance(rows[-1]["candidate_path"], str)
        stored = self.state / rows[-1]["candidate_path"]
        for target in (self.state / "proof.json", stored, self.evidence):
            with self.subTest(target=target):
                before = target.read_bytes()
                target.write_bytes(before + b" ")
                with self.assertRaisesRegex(suite.SuiteError, "proof_supersession_invalid"):
                    self.active()
                target.write_bytes(before)
        stored.unlink()
        stored.symlink_to(self.candidate)
        with self.assertRaisesRegex(suite.SuiteError, "proof_supersession_invalid"):
            self.active()
        stored.unlink()
        stored.write_bytes(self.candidate.read_bytes())
        results = self.state / pr.RESULTS_NAME
        raw = results.read_text()
        results.write_text(raw[:-2] + "X\n")
        with self.assertRaises(pr.ChainError):
            self.active()

    def test_foreign_or_duplicate_binding_row_blocks(self) -> None:
        """A hash-correct foreign or second binding cannot select a suite."""
        self.assertEqual(self.supersede(RUNNERS[0]).returncode, 0)
        results = self.state / pr.RESULTS_NAME
        original_row = json.loads(results.read_text())
        foreign = original_row | {"session_id": "foreign"}
        foreign["row_sha256"] = pr.sha(
            json.dumps(
                {key: value for key, value in foreign.items() if key != "row_sha256"},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        results.write_text(json.dumps(foreign) + "\n")
        with self.assertRaisesRegex(suite.SuiteError, "loop identity"):
            self.active()
        duplicate = original_row | {"seq": 2, "prev_sha256": original_row["row_sha256"]}
        duplicate["row_sha256"] = pr.sha(
            json.dumps(
                {key: value for key, value in duplicate.items() if key != "row_sha256"},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        results.write_text(json.dumps(original_row) + "\n" + json.dumps(duplicate) + "\n")
        with self.assertRaisesRegex(suite.SuiteError, "proof_supersession_duplicate"):
            self.active()

    def test_invalid_inputs_orphan_and_interrupted_append(self) -> None:
        """A failed append leaves only an inactive candidate file."""
        self.candidate.write_text('{"schema_version":1}')
        self.assertIn("proof_supersession_candidate_invalid", self.supersede(RUNNERS[0]).stderr)
        invalid: dict[str, Any] = {
            "schema_version": 2,
            **self.identity,
            "amendments": ["changed"],
            "proofs": [{"id": "NEW", "cmd": "true", "status": "satisfied", "expect": {}}],
        }
        self.candidate.write_text(json.dumps(invalid))
        self.assertIn("proof_supersession_candidate_invalid", self.supersede(RUNNERS[0]).stderr)
        self.candidate.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    **self.identity,
                    "amendments": [],
                    "proofs": [{"id": "NEW", "cmd": "true", "status": "pending", "expect": {}}],
                }
            )
        )
        self.evidence.write_bytes(b"")
        self.assertIn("proof_author_evidence_missing", self.supersede(RUNNERS[0]).stderr)
        self.evidence.write_text("report")
        inside = self.state / "inside-candidate.json"
        inside.write_bytes(self.candidate.read_bytes())
        result = self.cli(
            RUNNERS[0],
            "supersede",
            str(self.state),
            "--candidate",
            str(inside),
            "--reason",
            "why",
            "--original-sha256",
            hashlib.sha256(self.original).hexdigest(),
            "--author-evidence",
            str(self.evidence),
        )
        self.assertIn("proof_supersession_candidate_invalid", result.stderr)
        link = self.state / "linked-report"
        link.symlink_to(self.evidence)
        result = self.cli(
            RUNNERS[0],
            "supersede",
            str(self.state),
            "--candidate",
            str(self.candidate),
            "--reason",
            "why",
            "--original-sha256",
            hashlib.sha256(self.original).hexdigest(),
            "--author-evidence",
            str(link),
        )
        self.assertIn("proof_author_evidence_missing", result.stderr)
        with patch.object(pr, "append", side_effect=OSError("interrupted append")), self.assertRaises(suite.SuiteError):
            suite.supersede(self.state, self.candidate, "why", hashlib.sha256(self.original).hexdigest(), self.evidence)
        selected, rows, _ = self.active()
        self.assertEqual(selected, json.loads(self.original))
        self.assertFalse(rows)
        self.assertTrue(list((self.state / "proof_candidates").glob("*.json")))

    def test_wrong_identity_original_hash_and_symlink_candidate_refuse(self) -> None:
        """Invalid identity, original hash, or source link cannot start replacement."""
        original = self.candidate.read_bytes()
        self.candidate.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "session_id": "foreign",
                    "loop_id": self.identity["loop_id"],
                    "proofs": [{"id": "NEW", "cmd": "true", "expect": {}}],
                }
            )
        )
        self.assertIn("proof_supersession_candidate_invalid", self.supersede(RUNNERS[0]).stderr)
        self.candidate.write_bytes(original)
        result = self.cli(
            RUNNERS[0],
            "supersede",
            str(self.state),
            "--candidate",
            str(self.candidate),
            "--reason",
            "why",
            "--original-sha256",
            "0" * 64,
            "--author-evidence",
            str(self.evidence),
        )
        self.assertIn("proof_supersession_original_hash_mismatch", result.stderr)
        link = self.state / "linked-candidate"
        link.symlink_to(self.candidate)
        result = self.cli(
            RUNNERS[0],
            "supersede",
            str(self.state),
            "--candidate",
            str(link),
            "--reason",
            "why",
            "--original-sha256",
            hashlib.sha256(self.original).hexdigest(),
            "--author-evidence",
            str(self.evidence),
        )
        self.assertIn("proof_supersession_candidate_invalid", result.stderr)
        self.assertEqual((self.state / "proof.json").read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
