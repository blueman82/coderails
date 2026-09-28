"""Preserve structural, freeze and comment-embed refusal contracts."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ArtifactCase, entry
from scripts.lib.eval_validation import validate_embed, validate_structure


class StructureTests(ArtifactCase):
    """Reject malformed evidence before it can acquire an authoritative verdict."""

    def test_valid_suite_and_level_zero(self) -> None:
        """Accept actual content failures at freeze and justified unscripted level zero."""
        self.data["evals"] = [entry(), entry("E2")]
        self.save()
        validate_structure(self.path, "192", "head")
        self.data.update(verification_level=0, evals=[])
        self.save()
        validate_structure(self.path, "192", "head")

    def test_justification_matrix_and_order(self) -> None:
        """Every level requires a nonblank string before secondary checks run."""
        for level in (0, 1, 2):
            for justification in (None, "", " \t\n", 42):
                with self.subTest(level=level, justification=justification):
                    self.data.update(verification_level=level, verification_justification=justification, evals=[])
                    self.save()
                    with self.assertRaisesRegex(ValueError, f"verification_level {level}.*justification"):
                        validate_structure(self.path, "192", "wrong")
            self.data.pop("verification_justification")
            self.save()
            with self.assertRaisesRegex(ValueError, "verification_justification"):
                validate_structure(self.path, "192", "head")

    def test_empty_or_wrapped_controls(self) -> None:
        """Whitespace and command repetition cannot masquerade as a negative control."""
        item = entry()
        for control in (
            "",
            "  \n",
            item["cmd"],
            f"{item['cmd']}   ",
            f"true; {item['cmd']}",
            f"echo x && {item['cmd']}",
        ):
            with self.subTest(control=control):
                self.data["evals"] = [{**item, "negative_control": control}]
                self.save()
                with self.assertRaisesRegex(ValueError, "E1.*(empty|identical)"):
                    validate_structure(self.path, "192", "head")

    def test_evidence_head_and_priority_refusals(self) -> None:
        """Name the invalid evidence or SHA and require a P0 at nonzero levels."""
        self.data["evals"] = [{**entry(), "evidence": ""}]
        self.save()
        with self.assertRaisesRegex(ValueError, "P0.*E1.*evidence"):
            validate_structure(self.path, "192", "head")
        self.data["evals"] = [entry()]
        self.save()
        with self.assertRaisesRegex(ValueError, r"head.*wrong"):
            validate_structure(self.path, "192", "wrong")
        self.data["head_sha"] = ""
        self.save()
        with self.assertRaisesRegex(ValueError, "head_sha.*non-blank"):
            validate_structure(self.path, scope="loop")
        for evals in ([], [{**entry(), "priority": "P1"}]):
            self.data.update(head_sha="head", evals=evals)
            self.save()
            with self.assertRaisesRegex(ValueError, "P0"):
                validate_structure(self.path, "192", "head")

    def test_missing_malformed_file_and_cli_usage(self) -> None:
        """Fail through the real CLI on absent and malformed input."""
        self.path.unlink()
        result = self.cli("compute-result")
        self.assertEqual((result.returncode, result.stdout), (0, "NO-GO"))
        result = self.cli("validate-structure", "192", "head")
        self.assertEqual(result.returncode, 1)
        self.assertIn("evals.json", result.stderr)
        self.path.write_text("{broken")
        self.assertEqual(self.cli("validate-structure", "192", "head").returncode, 1)
        from scripts.post_evals import main

        self.assertEqual(main([]), 1)

    def test_freeze_ancestry_and_explicit_disclosure(self) -> None:
        """Use real Git history to distinguish the branch base from a late freeze."""
        base = self.repository()
        self.git("checkout", "-b", "feature")
        self.git("commit", "--allow-empty", "-m", "implementation")
        later = self.git("rev-parse", "HEAD")
        self.data["frozen_sha"] = base
        self.save()
        validate_structure(self.path, "192", "head")
        self.data["frozen_sha"] = later
        self.save()
        with self.assertRaisesRegex(ValueError, "late freeze"):
            validate_structure(self.path, "192", "head")
        validate_structure(self.path, scope="loop")
        self.data["verification_justification"] = "Explicit late freeze after implementation"
        self.save()
        validate_structure(self.path, "192", "head")
        self.data["frozen_sha"] = "f" * 40
        self.save()
        with self.assertRaisesRegex(ValueError, "does not resolve"):
            validate_structure(self.path, "192", "head")
        self.data.pop("frozen_sha")
        self.save()
        validate_structure(self.path, "192", "head")

    def test_embed_contract(self) -> None:
        """Require one matching level-zero JSON block and a well-formed marker."""
        valid = {"verification_level": 0, "task_ref": "192"}
        body = self.body(0, valid)
        validate_embed(self.path, body)
        marker = body.read_text().splitlines()[0]
        for text, reason in (
            (marker, "exactly one"),
            (body.read_text() + "```json\n{}\n```\n", "exactly one"),
            (f"{marker}\n```json\ninvalid\n```", "Expecting"),
            ("missing marker", "marker"),
        ):
            with self.subTest(reason=reason):
                body.write_text(text)
                with self.assertRaisesRegex(ValueError, reason):
                    validate_embed(self.path, body)
        for block, reason in (
            ({**valid, "verification_level": 2}, "verification_level"),
            ({**valid, "task_ref": "999"}, "task_ref"),
        ):
            with self.assertRaisesRegex(ValueError, reason):
                validate_embed(self.path, self.body(0, block))
        body = self.body(1, {})
        body.write_text(body.read_text().splitlines()[0])
        validate_embed(self.path, body)


if __name__ == "__main__":
    unittest.main()
