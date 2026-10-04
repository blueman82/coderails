"""Preserve eval structural refusals and trusted-commit execution boundaries."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.artifact_io import JsonObject
from scripts.lib.eval_execution import record_smoke, validate_smoke
from scripts.lib.eval_validation import validate_discriminating, validate_embed, validate_structure
from scripts.post_evals import smoke_verify


def fixture() -> JsonObject:
    """Return a valid scripted artifact with independent passing and failing commands."""
    return {
        "verification_level": 1,
        "verification_justification": "runtime boundary",
        "head_sha": "abc",
        "task_ref": "branch",
        "evals": [
            {
                "id": "E1",
                "mode": "scripted",
                "priority": "P0",
                "status": "pass",
                "evidence": "observed",
                "cmd": "exit 0",
                "negative_control": "exit 1",
                "smoke": {"cmd_exit": 0, "negative_control_exit": 1},
            }
        ],
    }


class EvalValidationTests(unittest.TestCase):
    """Exercise strict input structure and actual command behavior independently."""

    def setUp(self) -> None:
        """Keep freeze-time signing keys out of the real ~/.coderails/keys."""
        self.keys = tempfile.TemporaryDirectory()
        self.addCleanup(self.keys.cleanup)
        patcher = patch.dict(os.environ, {"CODERAILS_KEYS_DIR": self.keys.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_justification_control_evidence_sha_and_p0(self) -> None:
        """Reject each structural refusal using one independently mutated valid artifact."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            good = fixture()
            path.write_text(json.dumps(good))
            validate_structure(path, "1", "abc")
            for value in (None, "", "  ", 42):
                bad = copy.deepcopy(good)
                bad["verification_justification"] = value
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    validate_structure(path, "1", "abc")
            for key, value in (
                ("negative_control", ""),
                ("negative_control", " exit 0 "),
                ("negative_control", "true; exit 0"),
                ("negative_control", "echo x && exit 0"),
                ("evidence", ""),
                ("priority", "P1"),
            ):
                bad = copy.deepcopy(good)
                bad["evals"][0][key] = value
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    validate_structure(path, "1", "abc")
            path.write_text(json.dumps(good))
            with self.assertRaises(ValueError):
                validate_structure(path, "1", "wrong")
            malformed_cases: list[object] = ["bad", [{"id": "absent"}], [{}], ["bad"]]
            for new_cases in malformed_cases:
                bad = copy.deepcopy(good)
                bad["new_cases"] = new_cases
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    validate_structure(path, "1", "abc", "loop")

    def test_level_zero_and_embed_identity(self) -> None:
        """Require a single same-task JSON embed for the justified exemption path."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            body = Path(temporary) / "body.md"
            data = fixture()
            data.update(verification_level=0, evals=[])
            path.write_text(json.dumps(data))
            validate_structure(path, "1", "abc")
            marker = "<!-- coderails-eval-summary v1 pr=1 head_sha=abc result=GO verification_level=0 -->"
            body.write_text(marker + "\n```json\n" + json.dumps(data) + "\n```\n")
            validate_embed(path, body)
            for block in (
                {"verification_level": 1, "task_ref": "branch"},
                {"verification_level": 0, "task_ref": "other"},
            ):
                body.write_text(marker + "\n```json\n" + json.dumps(block) + "\n```\n")
                with self.assertRaises(ValueError):
                    validate_embed(path, body)
            body.write_text(marker + "\n```json\n{}\n```\n```json\n{}\n```\n")
            with self.assertRaises(ValueError):
                validate_embed(path, body)

    def test_smoke_record_and_fixture_discrimination(self) -> None:
        """Record real outcomes and reject vacuous or environmentally broken controls."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evals.json"
            data = fixture()
            path.write_text(json.dumps(data))
            record_smoke(path)
            recorded = json.loads(path.read_text())
            self.assertEqual(recorded["evals"][0]["smoke"]["negative_control_exit"], 1)
            validate_smoke(recorded)
            for code in (None, "1", 0, 126, 127, 137, 142):
                data = fixture()
                data["evals"][0]["smoke"]["negative_control_exit"] = code
                with self.assertRaises(ValueError):
                    validate_smoke(data)
            data = fixture()
            data["evals"][0]["cmd"] = "echo yes | grep -q yes"
            data["evals"][0]["fixtures"] = {"good": "yes", "bad": "no", "formula": "grep -q yes"}
            path.write_text(json.dumps(data))
            validate_discriminating(path)
            for formula in ("true", "false", "missing-coderails-command-xyz", "exit 137"):
                data["evals"][0]["fixtures"]["formula"] = formula
                data["evals"][0]["cmd"] = f"echo yes | {formula}"
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    validate_discriminating(path)

    def test_trusted_sha_excludes_uncommitted_priming(self) -> None:
        """A file present only in the caller checkout cannot satisfy the merge gate."""
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    temporary,
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.test",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "base",
                ],
                check=True,
            )
            head = subprocess.check_output(["git", "-C", temporary, "rev-parse", "HEAD"], text=True).strip()
            path = root / "evals.json"
            data = fixture()
            path.write_text(json.dumps(data))
            try:
                os.chdir(root)
                self.assertEqual(smoke_verify(path, head), 0)
                (root / "uncommitted-check").write_text("exit 0\n")
                data["evals"][0]["cmd"] = "bash uncommitted-check"
                path.write_text(json.dumps(data))
                self.assertEqual(smoke_verify(path, head), 1)
                worktrees = subprocess.check_output(["git", "worktree", "list", "--porcelain"], text=True)
                self.assertEqual(worktrees.count("worktree "), 1)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
