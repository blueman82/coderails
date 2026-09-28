"""Preserve observed smoke execution, stdin isolation and environmental refusals."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ArtifactCase, command, entry
from scripts.lib.eval_execution import (
    is_environmental_rc,
    record_smoke,
    run_recorded,
    validate_smoke,
    verify_execution,
)
from scripts.lib.eval_validation import validate_structure


class ExecutionTests(ArtifactCase):
    """Stored outcomes cannot substitute for the actual command and control."""

    def test_smoke_evidence_matrix(self) -> None:
        """Accept content failures and refuse crashes, missing commands and vacuous controls."""
        for key, code in (
            ("cmd_exit", 127),
            ("cmd_exit", 139),
            ("negative_control_exit", 0),
            ("negative_control_exit", 127),
            ("negative_control_exit", 142),
            ("cmd_exit", "zero"),
            ("cmd_exit", True),
        ):
            with self.subTest(key=key, code=code):
                item = entry()
                item["smoke"][key] = code
                with self.assertRaisesRegex(ValueError, "E1"):
                    validate_smoke({**self.data, "evals": [item]})
        malformed_smokes: tuple[object, ...] = (None, "malformed", {})
        for smoke in malformed_smokes:
            with self.subTest(smoke=smoke), self.assertRaisesRegex(ValueError, "E1"):
                validate_smoke({**self.data, "evals": [{**entry(), "smoke": smoke}]})
        for code in (0, 1):
            item = entry()
            item["smoke"]["cmd_exit"] = code
            validate_smoke({**self.data, "evals": [item]})

    def test_modes_collections_and_deliberate_skips(self) -> None:
        """Malformed collections and modes are rejected; explicit unscripted modes skip execution."""
        for operation in (validate_smoke, verify_execution):
            malformed_collections: tuple[object, ...] = (42, "bad", {}, None)
            for value in malformed_collections:
                with (
                    self.subTest(operation=operation.__name__, value=value),
                    self.assertRaisesRegex(ValueError, "evals.*array"),
                ):
                    operation({**self.data, "evals": value})
            for mode in (None, "Scripted", ""):
                with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "mode"):
                    operation({**self.data, "evals": [{**entry(), "mode": mode}]})
            operation({**self.data, "evals": [{**entry(), "mode": "agent-run", "smoke": None, "cmd": ""}]})
            operation({**self.data, "verification_level": 0, "evals": None})

    def test_smoke_records_actual_outcomes_and_preserves_metadata(self) -> None:
        """Replace optimistic evidence with observed return codes and output."""
        self.data["metadata"] = {"retain": [1, "text"]}
        self.data["evals"] = [
            {**entry(), "cmd": "coderails_nonexistent_eval_executable_3971"},
            {**entry("agent"), "mode": "agent-run"},
        ]
        self.data["evals"][1].pop("smoke")
        self.save()
        record_smoke(self.path)
        observed = self.reload()
        self.assertEqual(observed["evals"][0]["smoke"]["cmd_exit"], 127)
        self.assertTrue(observed["evals"][0]["smoke"]["cmd_output"])
        self.assertEqual(observed["metadata"], self.data["metadata"])
        self.assertNotIn("smoke", observed["evals"][1])
        with self.assertRaisesRegex(ValueError, "E1.*127"):
            validate_smoke(observed)
        self.data["evals"] = [entry()]
        self.save()
        record_smoke(self.path)
        observed = self.reload()
        self.assertEqual(observed["evals"][0]["smoke"]["cmd_output"], "check")
        validate_smoke(observed)
        self.data["evals"][0]["negative_control"] = command("print('passes')")
        self.save()
        record_smoke(self.path)
        with self.assertRaisesRegex(ValueError, "negative_control exited 0"):
            validate_smoke(self.reload())

    def test_non_string_id_refused_before_smoke_write(self) -> None:
        """A numeric identity cannot select a different entry during recording."""
        self.data["evals"] = [{**entry(), "id": 1}]
        self.data["evals"][0].pop("smoke")
        self.save()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "non-string id"):
            record_smoke(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_output_bounds_keep_head_and_tail(self) -> None:
        """Retain both the initial error and final verdict from chatty commands."""
        code, output = run_recorded(
            command("print('FATAL_HEAD_MARKER'); print('frame ' * 1000); print('TAIL_VERDICT_MARKER')")
        )
        self.assertEqual(code, 0)
        self.assertIn("FATAL_HEAD_MARKER", output)
        self.assertIn("TAIL_VERDICT_MARKER", output)
        self.assertLess(len(output), 700)

    def test_timeout_kills_process_group_without_waiting_for_descendant(self) -> None:
        """A subprocess holding inherited output cannot outlive the bounded wait."""
        source = (
            "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']).wait()"
        )
        start = time.monotonic()
        code, _ = run_recorded(command(source), timeout=0.3)
        self.assertEqual(code, 142)
        self.assertLess(time.monotonic() - start, 5)
        self.assertTrue(is_environmental_rc(code))
        self.assertFalse(is_environmental_rc(1))

    def test_current_directory_and_stdin_isolation(self) -> None:
        """Missing cwd is environmental; a valid cwd and empty default stdin are real execution."""
        self.assertEqual(run_recorded(command("raise SystemExit(1)"), cwd=self.directory)[0], 1)
        self.assertEqual(run_recorded(command("pass"), cwd=self.directory / "missing")[0], 127)
        self.assertEqual(run_recorded(command("import sys; print(sys.stdin.read(), end='')")), (0, ""))
        self.data["evals"] = [
            {**entry(f"E{i}"), "cmd": command("import sys; print(sys.stdin.read(), end='')")} for i in range(3)
        ]
        self.save()
        result = self.cli("smoke-run", stdin="untrusted caller input")
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = self.reload()["evals"]
        self.assertEqual(len(observed), 3)
        self.assertTrue(all(item["smoke"]["cmd_output"] == "" for item in observed))

    def test_gate_reexecutes_instead_of_trusting_smoke(self) -> None:
        """Plausible frozen outcomes cannot make absent or vacuous commands pass."""
        for key, value, reason in (
            ("cmd", "coderails_missing_command_3971", "cmd did not execute at the gate"),
            ("negative_control", "coderails_missing_control_3971", "negative_control did not execute at the gate"),
            ("negative_control", command("pass"), "negative_control exited 0 at the gate"),
            ("cmd", "", "empty cmd"),
            ("cmd", " \t", "empty cmd"),
        ):
            with self.subTest(key=key, value=value):
                self.data["evals"] = [{**entry(), key: value}]
                self.save()
                with self.assertRaisesRegex(ValueError, f"E1.*{reason}"):
                    validate_structure(self.path, "192", "head")
                validate_structure(self.path, scope="loop")
        for code in (0, 1):
            verify_execution({**self.data, "evals": [{**entry(), "cmd": command(f"raise SystemExit({code})")}]})

    def test_duplicate_ids_and_stdin_eaters_do_not_skip_later_entries(self) -> None:
        """Visit every entry by position and prove the second control actually ran."""
        for entries, reason in (
            ([{**entry(), "cmd": "coderails_missing_duplicate_3971"}, entry()], "E1.*cmd did not execute"),
            ([entry(), {**entry(), "cmd": "coderails_missing_duplicate_3971"}], "E1.*cmd did not execute"),
            (
                [
                    {**entry("stdin"), "cmd": command("import sys; sys.stdin.read()")},
                    {**entry("vacuous"), "negative_control": command("pass")},
                ],
                "vacuous.*negative_control exited 0",
            ),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                verify_execution({**self.data, "evals": entries})


if __name__ == "__main__":
    unittest.main()
