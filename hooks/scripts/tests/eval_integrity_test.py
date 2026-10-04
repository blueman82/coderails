"""Tamper-evidence, grader identity, control execution and trace rows for frozen eval suites."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_evals import read_loop_evals_result
from hooks.scripts.tests.lib.post_evals_fixture import ROOT, ArtifactCase, command, entry
from scripts.lib import eval_trace
from scripts.lib.artifact_io import read_object
from scripts.lib.eval_execution import record_smoke, verify_execution
from scripts.lib.eval_integrity import IntegrityError, append_amendment, suite_hash, verify_suite
from scripts.lib.eval_validation import validate_discriminating
from scripts.post_evals import grade_loop


def code_of(case: unittest.TestCase, call: Callable[[], object]) -> str:
    """Return the reason code of the IntegrityError the call must raise."""
    with case.assertRaises(IntegrityError) as caught:
        call()
    return str(caught.exception.code)


def quiet() -> contextlib.redirect_stderr[io.StringIO]:
    """Silence the reason lines grade-loop prints."""
    return contextlib.redirect_stderr(io.StringIO())


class Base(ArtifactCase):
    """A suite frozen through the real freeze-time recorder."""

    def setUp(self) -> None:
        """Setup."""
        super().setUp()
        self.freeze()

    def freeze(self) -> None:
        """Re-run the freeze-time recorder and reload."""
        record_smoke(self.path)
        self.data = self.reload()

    def edit_cmd(self, text: str) -> None:
        """Rewrite the oracle in place, as a model would."""
        self.data = self.reload()
        self.data["evals"][0]["cmd"] = text
        self.save()


class SuiteHashTests(Base):
    """Oracle contents are bound; legitimately mutable fields are not."""

    def test_record_smoke_stamps_frozen_hash(self) -> None:
        """Test record smoke stamps frozen hash."""
        self.assertEqual(self.data["frozen_hash"], suite_hash(self.data))

    def test_mutable_fields_do_not_change_hash(self) -> None:
        """Test mutable fields do not change hash."""
        before = suite_hash(self.data)
        self.data["evals"][0].update(status="fail", evidence="other", smoke={"cmd_exit": 9})
        self.data.update(result="GO", graded_at="x", grading={"by": "x"}, amendments=[{"why": "w"}])
        self.assertEqual(suite_hash(self.data), before)

    def test_oracle_substitution_at_same_sha(self) -> None:
        """Swapping cmd text while head_sha stays equal is refused at grade."""
        self.edit_cmd(command("raise SystemExit(0)"))
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "suite_hash_mismatch")
        self.assertNotIn("grading", self.reload())

    def test_same_sha_mutation_of_control_and_fixtures(self) -> None:
        """Test same sha mutation of control and fixtures."""
        for key, value in (
            ("negative_control", command("raise SystemExit(3)")),
            ("fixtures", {"good": "a", "bad": "b"}),
        ):
            with self.subTest(key=key):
                self.data = self.reload()
                self.data["evals"][0][key] = value
                self.save()
                self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "suite_hash_mismatch")
                self.data["evals"][0].pop(key)
                self.data["evals"][0]["negative_control"] = entry()["negative_control"]
                self.save()

    def test_amend_records_edit_and_grade_passes(self) -> None:
        """Test amend records edit and grade passes."""
        self.edit_cmd(command("print('fixed')"))
        append_amendment(self.data, "E1", "cmd was wrong", "orchestrator")
        self.save()
        self.assertEqual(verify_suite(self.reload()), "verified")
        self.assertEqual(grade_loop(self.path), "GO")
        graded = self.reload()["grading"]
        self.assertEqual(graded["suite_hash"], suite_hash(self.reload()))
        self.assertEqual(graded["chain_len"], 1)
        self.assertEqual(graded["integrity"], "verified")


class ChainTests(Base):
    """Break, reorder and truncation are detected."""

    def amended(self, count: int = 2) -> None:
        """Amended."""
        for number in range(count):
            self.data["evals"][0]["cmd"] = command(f"print({number})")
            append_amendment(self.data, "E1", f"change {number}", "orchestrator")
        self.save()

    def test_break(self) -> None:
        """Test break."""
        self.amended()
        self.data["amendment_chain"][0]["reason"] = "rewritten"
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload())), "chain_broken")

    def test_reorder(self) -> None:
        """Test reorder."""
        self.amended()
        chain = self.data["amendment_chain"]
        chain[0], chain[1] = chain[1], chain[0]
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload())), "chain_broken")

    def test_truncation_with_oracle_change(self) -> None:
        """Test truncation with oracle change."""
        self.amended()
        self.data["amendment_chain"].pop()
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload())), "suite_hash_mismatch")

    def test_truncation_after_grade_is_chain_truncated(self) -> None:
        """Test truncation after grade is chain truncated."""
        self.amended()
        grade_loop(self.path)
        self.data = self.reload()
        self.data["amendment_chain"].pop()
        self.save()
        self.assertEqual(code_of(self, lambda: verify_suite(self.reload())), "chain_truncated")

    def test_chain_without_frozen_hash_is_broken(self) -> None:
        """Test chain without frozen hash is broken."""
        self.amended(1)
        self.data.pop("frozen_hash")
        self.assertEqual(code_of(self, lambda: verify_suite(self.data)), "chain_broken")


class LegacyTests(ArtifactCase):
    """An unhashed suite grades, but never silently."""

    def test_legacy_unhashed_is_stamped_traced_and_printed(self) -> None:
        """Test legacy unhashed is stamped traced and printed."""
        self.assertNotIn("frozen_hash", self.reload())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(grade_loop(self.path), "GO")
        self.assertIn("reason=legacy_unhashed", err.getvalue())
        self.assertEqual(self.reload()["grading"]["integrity"], "legacy_unhashed")
        rows = [json.loads(line) for line in (self.directory / "eval_trace.jsonl").read_text().splitlines()]
        self.assertIn(
            ("grade-loop", "legacy", "legacy_unhashed"),
            [(r["command"], r["outcome"], r["reason_code"]) for r in rows],
        )

    def test_legacy_oracle_edit_after_grade_detected_by_reader(self) -> None:
        """Test legacy oracle edit after grade detected by reader."""
        self.data.update(scope="loop")
        self.save()
        with quiet():
            grade_loop(self.path)
            self.assertEqual(read_loop_evals_result(self.directory), "GO")
            self.data = self.reload()
            self.data["evals"][0]["cmd"] = command("raise SystemExit(0)")
            self.save()
            self.assertEqual(read_loop_evals_result(self.directory), "TAMPERED:suite_hash_mismatch")


class HashedReaderTests(Base):
    """The merge/completion reader re-verifies hashed suites."""

    def setUp(self) -> None:
        """Freeze a loop-scope suite (scope is part of the hashed oracle)."""
        ArtifactCase.setUp(self)
        self.data.update(scope="loop")
        self.save()
        self.freeze()

    def test_reader_detects_oracle_edit_after_grade(self) -> None:
        """Test reader detects oracle edit after grade."""
        grade_loop(self.path)
        self.assertEqual(read_loop_evals_result(self.directory), "GO")
        self.edit_cmd(command("raise SystemExit(0)"))
        self.assertEqual(read_loop_evals_result(self.directory), "TAMPERED:suite_hash_mismatch")


class IdentityTests(ArtifactCase):
    """grade-loop fails closed on its own identity source."""

    def progress(self) -> Path:
        """Path of the sibling progress.json."""
        return self.directory / "progress.json"

    def test_missing(self) -> None:
        """Test missing."""
        self.progress().unlink()
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "progress_missing")
        self.assertNotIn("grading", self.reload())

    def test_unparseable_and_idless(self) -> None:
        """Test unparseable and idless."""
        for text in ("{not json", "{}", '{"session_id":"s"}'):
            with self.subTest(text=text):
                self.progress().write_text(text)
                self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "progress_unparseable")

    def test_foreign(self) -> None:
        """Test foreign."""
        self.data.update(session_id="other", loop_id="l")
        self.save()
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "progress_foreign")
        self.data.update(session_id="s", loop_id="other")
        self.save()
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "progress_foreign")

    def test_schema_two_allowed_and_traced(self) -> None:
        """Test schema two allowed and traced."""
        self.progress().write_text('{"schema_version":2,"session_id":"s","loop_id":"l"}')
        with quiet():
            self.assertEqual(grade_loop(self.path), "GO")
        self.assertIn("legacy_progress_schema", (self.directory / "eval_trace.jsonl").read_text())

    def test_cli_prints_reason_and_traces_refusal(self) -> None:
        """Test cli prints reason and traces refusal."""
        self.progress().unlink()
        result = self.cli("grade-loop")
        self.assertEqual(result.returncode, 1)
        self.assertIn("reason=progress_missing", result.stderr)
        row = json.loads((self.directory / "eval_trace.jsonl").read_text().splitlines()[-1])
        self.assertEqual((row["outcome"], row["reason_code"]), ("refuse", "progress_missing"))


class ControlTests(ArtifactCase):
    """Loop-scope controls are executed at grade time."""

    def test_control_exit_zero(self) -> None:
        """Test control exit zero."""
        self.data["evals"][0]["negative_control"] = command("print('ok')")
        self.save()
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "control_passes")
        self.assertNotIn("grading", self.reload())

    def test_control_environmental(self) -> None:
        """Test control environmental."""
        self.data["evals"][0]["negative_control"] = "definitely-not-a-command-xyz"
        self.save()
        self.assertEqual(code_of(self, lambda: grade_loop(self.path)), "control_env")

    def test_content_failure_accepted_and_level_zero_skipped(self) -> None:
        """Test content failure accepted and level zero skipped."""
        with quiet():
            self.assertEqual(grade_loop(self.path), "GO")
            self.data.update(verification_level=0, evals=[])
            self.save()
            self.assertEqual(grade_loop(self.path), "GO")


class GateTests(ArtifactCase):
    """Forged PASS and fixture formulas."""

    def test_forged_pass_with_failing_cmd(self) -> None:
        """Test forged pass with failing cmd."""
        self.data["evals"][0]["cmd"] = command("raise SystemExit(1)")
        self.assertEqual(code_of(self, lambda: verify_execution(self.data)), "pass_exit_nonzero")
        self.data["evals"][0]["status"] = "fail"
        verify_execution(self.data)

    def test_freeze_time_exit_one_still_accepted(self) -> None:
        """Test freeze time exit one still accepted."""
        self.data["evals"][0].update(cmd=command("raise SystemExit(1)"), status="pending")
        self.save()
        record_smoke(self.path)
        self.assertEqual(self.reload()["evals"][0]["smoke"]["cmd_exit"], 1)

    def test_fixture_formula_must_be_suffix_of_cmd(self) -> None:
        """Test fixture formula must be suffix of cmd."""
        formula = command("import sys; sys.exit(0 if sys.stdin.read()=='good' else 1)")
        item = self.data["evals"][0]
        item["fixtures"] = {"good": "good", "bad": "bad", "formula": formula}
        item["cmd"] = "echo unrelated"
        self.save()
        self.assertEqual(code_of(self, lambda: validate_discriminating(self.path)), "fixture_formula_not_in_cmd")
        item["cmd"] = "cat x | " + formula
        self.save()
        validate_discriminating(self.path)


class TraceTests(ArtifactCase):
    """Rows are complete, hashed and fail-open."""

    def test_row_shape_and_no_raw_content(self) -> None:
        """Test row shape and no raw content."""
        eval_trace.emit(self.path, "grade-loop", "refuse", "control_passes")
        row = json.loads((self.directory / "eval_trace.jsonl").read_text())
        self.assertEqual(
            set(row),
            {
                "schema_version",
                "session_id",
                "loop_id",
                "timestamp",
                "command",
                "outcome",
                "reason_code",
                "event_id",
                "inputs",
            },
        )
        self.assertEqual((row["session_id"], row["loop_id"]), ("s", "l"))
        self.assertRegex(row["inputs"]["evals_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("Observed command", json.dumps(row))

    def test_fail_open(self) -> None:
        """Test fail open."""
        with patch("builtins.open", side_effect=OSError("denied")):
            eval_trace.emit(self.path, "grade-loop", "refuse", "x")
        eval_trace.emit(self.directory / "missing" / "evals.json", "grade-loop", "refuse", "x")

    def test_mirror_is_byte_identical(self) -> None:
        """Test mirror is byte identical."""
        for name in ("lib/eval_integrity.py", "lib/eval_trace.py", "lib/eval_execution.py", "post_evals.py"):
            self.assertEqual(
                (ROOT / "scripts" / name).read_bytes(), (ROOT / "packages/codex/scripts" / name).read_bytes()
            )


class AmendCliTests(Base):
    """The amend operation records an in-place edit on the chain."""

    def test_amend_operation(self) -> None:
        """Test amend operation."""
        self.edit_cmd(command("print('v2')"))
        result = self.cli("amend", "E1", "why", "me")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = read_object(self.path)
        self.assertEqual(len(data["amendment_chain"]), 1)
        self.assertEqual(data["amendments"][0]["why"], "why")
        self.assertEqual(verify_suite(data), "verified")


if __name__ == "__main__":
    unittest.main()
