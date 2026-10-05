"""Verify the review fixes to the diff-manifest checker: quoting, case, file type, fail-open gate, trace keys."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_policy  # noqa: E402
from scripts.tests.manifest_policy_test import RepoCase, git_cmd  # noqa: E402


class ReviewFixTests(RepoCase):
    """Review findings: quoting, case, file type, fail-open gate, trace keys."""

    def test_quoted_path_is_unquoted(self) -> None:
        """A C-quoted non-ASCII path still hits the deny rule."""
        rows = manifest_policy.parse_name_status('A\t"docs/\\303\\251.md"')
        self.assertFalse(manifest_policy.check(rows, {"deny": ["docs/**"]})["ok"])

    def test_real_diff_non_ascii_path(self) -> None:
        """Git diff output for a non-ASCII path matches a deny glob end to end."""
        (self.dir / "docs").mkdir()
        (self.dir / "docs" / "\u00e9.md").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "e")
        with mock.patch.object(git, "main", return_value="main"):
            old = os.getcwd()
            os.chdir(self.dir)
            try:
                changes = manifest_policy.diff_changes("HEAD")
            finally:
                os.chdir(old)
        self.assertFalse(manifest_policy.check(changes or [], {"deny": ["docs/**"]})["ok"])

    def test_case_insensitive_match(self) -> None:
        """Docs/x names the same file as docs/x on a case-insensitive checkout."""
        self.assertFalse(manifest_policy.check([("A", ["Docs/x"])], {"deny": ["docs/**"]})["ok"])
        self.assertTrue(manifest_policy.check([("M", ["SRC/a.py"])], {}, ["src/**"])["ok"])

    def test_symlink_and_gitlink_flagged(self) -> None:
        """Type changes and symlink/gitlink destinations are violations even at an in-manifest path."""
        raw = ":100644 120000 a b T\0src/a\0:000000 160000 a b A\0src/m\0:000000 100644 a b A\0src/ok\0"
        changes = manifest_policy.parse_raw_z(raw)
        result = manifest_policy.check(changes, {}, ["src/**"])
        self.assertEqual(
            sorted((v["code"], v["path"]) for v in result["violations"]),
            [("special_file_type", "src/a"), ("special_file_type", "src/m")],
        )

    def test_raw_z_rename(self) -> None:
        """Rename records carry source then destination."""
        self.assertEqual(manifest_policy.parse_raw_z(":100644 100644 a b R100\0a b\0c\0"), [("R100", ["a b", "c"])])

    def test_gate_fails_open_on_unexpected_error(self) -> None:
        """Advisory never aborts: a non-list manifest or a crash only traces failed_open."""
        cfg = self.dir.parent / "c.yaml"
        bad = self.policy({"manifest": "docs/**"})
        cfg.write_text(f"diff_manifest: advisory\ndiff_manifest_policy: {bad}\n")
        with (
            mock.patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
            mock.patch.object(manifest_policy, "config_path", return_value=str(cfg)),
        ):
            manifest_policy.gate()
            with mock.patch.object(manifest_policy, "diff_changes", side_effect=RuntimeError("boom")):
                manifest_policy.gate()
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        self.assertEqual([(r["outcome"], r["reason_code"]) for r in rows], [("failed_open", "manifest_unreadable")] * 2)

    def test_empty_pr_head_is_unreadable(self) -> None:
        """An unresolvable PR head never diffs the local HEAD: enforce refuses with manifest_unreadable."""
        cfg = self.dir.parent / "c.yaml"
        pol = self.policy({"manifest": ["docs/**"]})
        cfg.write_text(f"diff_manifest: enforce\ndiff_manifest_policy: {pol}\n")
        (self.dir / "c.py").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "c")
        old = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, old)
        with (
            mock.patch.object(manifest_policy, "config_path", return_value=str(cfg)),
            mock.patch.object(git, "pr_field", return_value=""),
            self.assertRaises(git.WorkflowError) as caught,
        ):
            manifest_policy.gate("5")
        self.assertEqual(str(caught.exception), "diff_manifest:manifest_unreadable")

    def test_unreadable_trace_key_matches_runbook(self) -> None:
        """Advisory gate and CLI both write failed_open/manifest_unreadable; CLI writes the ok row."""
        cfg = self.dir.parent / "c.yaml"
        cfg.write_text(f"diff_manifest: advisory\ndiff_manifest_policy: {self.dir}/nope.json\n")
        old = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, old)
        with (
            mock.patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
            mock.patch.object(manifest_policy, "config_path", return_value=str(cfg)),
        ):
            manifest_policy.gate()
        self.cli("--policy", self.policy({"allow": ["**"]}))
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        keys = [(r["outcome"], r["reason_code"]) for r in rows]
        self.assertIn(("failed_open", "manifest_unreadable"), keys)
        self.assertIn(("ok", "diff_manifest_ok"), keys)

    def test_gate_legacy_row_when_no_manifest(self) -> None:
        """A policy without a manifest key writes legacy/manifest_legacy_absent."""
        cfg = self.dir.parent / "c.yaml"
        cfg.write_text(f"diff_manifest: advisory\ndiff_manifest_policy: {self.policy({'allow': ['**']})}\n")
        old = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, old)
        with (
            mock.patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)}),
            mock.patch.object(manifest_policy, "config_path", return_value=str(cfg)),
        ):
            manifest_policy.gate()
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        self.assertIn(("legacy", "manifest_legacy_absent"), [(r["outcome"], r["reason_code"]) for r in rows])


if __name__ == "__main__":
    unittest.main()
