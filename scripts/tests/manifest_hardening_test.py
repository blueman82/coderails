"""Review findings on the default manifest policy: unit/progress mismatch, config errors, wider denylist, merge pin."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import merge  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_policy, publication_gate  # noqa: E402
from scripts.tests import manifest_default_test as base  # noqa: E402

SECRET = ".en" + "v"  # two parts so no source line spells the secret-file name
SHAPES = (
    SECRET + ".local", SECRET + ".production", "a/server.key", "c.p12", "credentials-prod.json", ".npmrc", ".netrc",
    ".git-credentials", "id_ed25519", "id_ecdsa.pub", ".coderails/workflow.config.yaml",
    "policy/diff-policy.default.json",
    "packages/codex/policy/diff-policy.default.json",
)  # fmt: skip


class DenylistTests(unittest.TestCase):
    """The shipped default policy, applied through check()."""

    policy = json.loads((REPO / "policy/diff-policy.default.json").read_text())

    def test_secret_shaped_paths_are_denied(self) -> None:
        """Every shape is denied_path; a plain doc is not (negative control)."""
        for path in SHAPES:
            with self.subTest(path=path):
                codes = [v["code"] for v in manifest_policy.check([("M", [path])], self.policy)["violations"]]
                self.assertEqual(codes, ["denied_path"])
        self.assertTrue(manifest_policy.check([("M", ["docs/guide.md"])], self.policy)["ok"])

    def test_deleting_a_secret_is_not_refused(self) -> None:
        """Removing a secret-shaped file is the safe direction, not a false positive."""
        self.assertTrue(manifest_policy.check([("D", [SECRET])], self.policy)["ok"])

    def test_mode_change_is_refused(self) -> None:
        """A chmod (100644 -> 100755) is mode_change; a plain edit of the same file is clean."""
        chmod = ":100644 100755 a b M\0x.sh\0"
        edit = ":100644 100644 a b M\0x.sh\0"
        self.assertEqual(manifest_policy.parse_raw_z(chmod), [("M:mode", ["x.sh"])])
        codes = [
            v["code"] for v in manifest_policy.check(manifest_policy.parse_raw_z(chmod), self.policy)["violations"]
        ]
        self.assertEqual(codes, ["mode_change"])
        self.assertTrue(manifest_policy.check(manifest_policy.parse_raw_z(edit), self.policy)["ok"])


class UnitMismatchTests(base.DefaultGateTests):
    """--unit without --progress (or the reverse) is refused under enforce, never silently ignored."""

    def test_mismatch_refused_and_control(self) -> None:
        """Enforce refuses a lone flag; advisory and a complete pair do not."""
        self.commit("docs/guide.md")
        for kwargs in ({"unit": "2"}, {"progress": "p.json"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.refusal(**kwargs), "diff_manifest:manifest_unreadable")
        self.gate("diff_manifest: advisory\n", unit="2")
        progress = self.dir.parent / "progress.json"
        progress.write_text(
            json.dumps(
                {
                    "session_id": "s",
                    "loop_id": "l",
                    "work_units": {"2": {"manifest": ["**/*.md"], "worktree": str(self.dir)}},
                }
            )
        )
        self.gate(unit="2", progress=str(progress))

    def test_requested_unit_requires_manifest(self) -> None:
        """An explicitly requested unit cannot discard its manifest bound."""
        self.commit("docs/guide.md")
        progress = self.dir.parent / "progress.json"
        progress.write_text(
            json.dumps(
                {
                    "session_id": "s",
                    "loop_id": "l",
                    "work_units": {"2": {"status": "pending", "worktree": str(self.dir)}},
                }
            )
        )
        self.assertEqual(self.refusal(unit="2", progress=str(progress)), "diff_manifest:manifest_unreadable")

    def test_unit_binding_requires_owner_shape_and_matching_worktree(self) -> None:
        """Missing owner metadata or a foreign worktree refuses; an empty manifest permits no paths."""
        self.commit("docs/guide.md")
        progress = self.dir.parent / "progress.json"
        entry: dict[str, object] = {"manifest": ["docs/**"], "worktree": str(self.dir)}
        valid = {"session_id": "s", "loop_id": "l", "work_units": {"2": entry}}
        for state in (
            {**valid, "session_id": ""},
            {**valid, "loop_id": None},
            {**valid, "work_units": {"2": {"manifest": ["docs/**"], "worktree": str(self.dir.parent)}}},
        ):
            with self.subTest(state=state):
                progress.write_text(json.dumps(state))
                self.assertEqual(self.refusal(unit="2", progress=str(progress)), "diff_manifest:manifest_unreadable")
        progress.write_text(json.dumps(valid))
        self.gate(unit="2", progress=str(progress))
        entry["manifest"] = []
        progress.write_text(json.dumps(valid))
        self.assertEqual(self.refusal(unit="2", progress=str(progress)), "diff_manifest:out_of_manifest")

    def test_config_load_error_is_internal_error(self) -> None:
        """A config that cannot be loaded refuses with manifest_internal_error instead of a raw exception."""
        self.commit("docs/guide.md")
        with mock.patch.object(manifest_policy, "load_config", side_effect=RuntimeError("boom")):
            self.assertEqual(self.refusal(), "diff_manifest:manifest_internal_error")
            self.assertEqual(
                [v["code"] for v in manifest_policy.violations()], ["diff_manifest:manifest_internal_error"]
            )
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        self.assertIn(("refused", "manifest_internal_error"), [(r["outcome"], r["reason_code"]) for r in rows])

    def test_real_unreadable_config_is_refused(self) -> None:
        """The loader reports unreadability as a finding rather than raising."""
        self.commit("docs/guide.md")
        with mock.patch.object(manifest_policy, "config_path", return_value=str(self.dir / "missing.yaml")):
            self.assertEqual(manifest_policy.violations()[0]["code"], "diff_manifest:manifest_internal_error")

    def test_explicit_empty_mode_reports_invalid_enforcement(self) -> None:
        """An explicitly empty mode is invalid, even though enforcement remains the default."""
        self.commit("docs/guide.md")
        self.gate("diff_manifest:\n")
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        self.assertIn("diff_manifest_mode_invalid", [r["reason_code"] for r in rows])

    def test_typed_null_policy_uses_the_shipped_default(self) -> None:
        """The existing config grammar coerces an empty nullable scalar to null."""
        self.commit("docs/guide.md")
        self.gate("diff_manifest_policy: ''\n")

    def test_unit_cannot_widen_policy_manifest(self) -> None:
        """Both declared bounds apply, and unknown or malformed requested units refuse."""
        self.commit("docs/guide.md")
        policy = self.dir.parent / "bounded.json"
        policy.write_text(json.dumps({"manifest": ["a.md"]}))
        progress = self.dir.parent / "progress.json"
        config = f"diff_manifest_policy: {policy}\n"
        for entry in ({"manifest": ["**"]}, None, {"manifest": "**"}):
            units = {} if entry is None else {"2": {**entry, "worktree": str(self.dir)}}
            progress.write_text(json.dumps({"session_id": "s", "loop_id": "l", "work_units": units}))
            self.assertEqual(
                self.refusal(config, unit="2", progress=str(progress)),
                (
                    "diff_manifest:out_of_manifest"
                    if entry == {"manifest": ["**"]}
                    else "diff_manifest:manifest_unreadable"
                ),
            )
        policy.write_text(json.dumps({"manifest": ["docs/**"]}))
        progress.write_text(
            json.dumps(
                {
                    "session_id": "s",
                    "loop_id": "l",
                    "work_units": {"2": {"manifest": ["**"], "worktree": str(self.dir)}},
                }
            )
        )
        self.gate(config, unit="2", progress=str(progress))

    def test_custom_policy_keeps_default_denials(self) -> None:
        """A custom manifest cannot allow a default-denied path."""
        self.commit(SECRET)
        policy = self.dir.parent / "custom.json"
        policy.write_text(json.dumps({"manifest": ["**"]}))
        self.assertEqual(self.refusal(f"diff_manifest_policy: {policy}\n"), "diff_manifest:denied_path")


class MergePinTests(unittest.TestCase):
    """merge.py pins the merge to the head the gate checked."""

    def test_merge_passes_match_head_commit(self) -> None:
        """The merge carries --match-head-commit with the checked head even if the remote head moves."""
        calls: list[tuple[str, ...]] = []
        heads = iter(("sha7", "unchecked"))

        def fake_run(*argv: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        def field(number: str, name: str, fallback: str = "") -> str:
            return next(heads) if name == "headRefOid" else {"state": "OPEN"}.get(name, fallback)

        with (
            mock.patch.object(git, "gate_review_summary_for_pr", return_value=(0, "")),
            mock.patch.object(git, "gate_eval_summary_for_pr", return_value=git.EvalSummary(0, "0", "{}")),
            mock.patch.object(merge, "smoke_verify", return_value=0),
            mock.patch.object(merge, "config_path", return_value=""),
            mock.patch.object(merge, "has_wiki_ingest_for_merged_prs"),
            mock.patch.object(git, "require_repo"),
            mock.patch.object(git, "main", return_value="main"),
            mock.patch.object(git, "pr_field", side_effect=field),
            mock.patch.object(git, "protected", return_value=False),
            mock.patch.object(git, "run", side_effect=fake_run),
            mock.patch.object(merge, "cleanup"),
            mock.patch.object(publication_gate, "enforce"),
        ):
            self.assertEqual(merge.main(["7"]), 0)
        merged = [c for c in calls if c[:3] == ("gh", "pr", "merge")]
        self.assertEqual(merged, [("gh", "pr", "merge", "7", "--merge", "--match-head-commit", "sha7")])


class MirrorTests(unittest.TestCase):
    """New and changed shared files stay byte-identical in the Codex package."""

    def test_mirrors(self) -> None:
        """Library and policy mirrors match; the Codex merge.py (different command names) pins the head too."""
        for name in ("scripts/lib/merge_target.py", "scripts/lib/manifest_policy.py"):
            self.assertEqual((REPO / name).read_bytes(), (REPO / "packages/codex" / name).read_bytes(), name)
        self.assertIn("--match-head-commit", (REPO / "packages/codex/scripts/merge.py").read_text())
        name = "policy/diff-policy.default.json"
        self.assertEqual((REPO / name).read_bytes(), (REPO / "packages/codex" / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
