"""Diff manifest as default-enforced policy: typed config, shipped policies, new check keys, controls."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from packages.tests.graph_manifest_fixture import graph_progress  # noqa: E402
from scripts.lib import config, manifest_policy  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.tests.manifest_policy_test import RepoCase, git_cmd  # noqa: E402

POLICIES = ("diff-policy.default.json", "docs-sync.policy.json", "retro-promotion.policy.json")
SECRET = ".en" + "v"  # built in two parts so no source line spells the secret-file name


class TypedConfigTests(unittest.TestCase):
    """The two keys are in the schema, so the loader no longer reports them as unknown."""

    def test_defaults_without_a_config_file(self) -> None:
        """No config file: diff_manifest=enforce and the policy is null (meaning the shipped default)."""
        values, findings = config.load_config("")
        self.assertEqual((values["diff_manifest"], values["diff_manifest_policy"]), ("enforce", None))
        self.assertEqual(findings, [])

    def test_keys_are_not_unknown(self) -> None:
        """A config naming both keys yields no config_unknown_key finding."""
        path = Path(os.environ.get("TMPDIR", "/tmp")) / "manifest_default_cfg.yaml"
        path.write_text("diff_manifest: advisory\ndiff_manifest_policy: p.json\n")
        self.addCleanup(path.unlink)
        values, findings = config.load_config(path)
        self.assertEqual((values["diff_manifest"], values["diff_manifest_policy"]), ("advisory", "p.json"))
        self.assertNotIn("config_unknown_key", [f["code"] for f in findings])


class ShippedPolicyTests(unittest.TestCase):
    """Policy files exist, parse, and are byte mirrors in the Codex package."""

    def test_files_exist_and_mirror(self) -> None:
        """Each shipped policy parses as a JSON object and the Codex copy is byte-identical."""
        for name in POLICIES:
            root = REPO / "policy" / name
            self.assertIsInstance(json.loads(root.read_text()), dict, name)
            self.assertEqual(root.read_bytes(), (REPO / "packages/codex/policy" / name).read_bytes(), name)

    def test_config_schema_mirror(self) -> None:
        """The schema is byte-identical in both packages."""
        root, codex = REPO / "config.schema.json", REPO / "packages/codex/config.schema.json"
        self.assertEqual(root.read_bytes(), codex.read_bytes())

    def test_retro_and_docs_sync_contents(self) -> None:
        """Retro promotion may only modify one named file; docs-sync mirrors SKILL.md step 4."""
        retro = json.loads((REPO / "policy/retro-promotion.policy.json").read_text())
        self.assertEqual(
            (retro["manifest"], retro["statuses"], retro["max_paths"]),
            (["skills/agentic-loop/learned-failure-modes.md"], ["M"], 1),
        )
        docs = json.loads((REPO / "policy/docs-sync.policy.json").read_text())["docs_sync"]
        self.assertEqual(docs["allow"], ["**/*.md"])
        self.assertIn("skills/**/SKILL.md", docs["deny"])
        self.assertIn(".claude/**", docs["deny"])


class CheckKeyTests(unittest.TestCase):
    """statuses and max_paths in manifest_policy.check."""

    policy: dict[str, Any] = {"manifest": ["a.md"], "statuses": ["M"], "max_paths": 1}

    def test_added_status_refused(self) -> None:
        """An A where only M is allowed reports status_not_allowed."""
        result = manifest_policy.check([("A", ["a.md"])], self.policy, ["a.md"])
        self.assertEqual([v["code"] for v in result["violations"]], ["status_not_allowed"])

    def test_second_path_refused(self) -> None:
        """A second path reports too_many_paths."""
        result = manifest_policy.check([("M", ["a.md"]), ("M", ["a.md2"])], {**self.policy, "manifest": ["a.md*"]})
        self.assertEqual([v["code"] for v in result["violations"]], ["too_many_paths"])

    def test_single_modified_path_passes(self) -> None:
        """Negative control: one M at the manifest path is clean."""
        self.assertTrue(manifest_policy.check([("M", ["a.md"])], self.policy, ["a.md"])["ok"])


class DefaultGateTests(RepoCase):
    """manifest_policy.gate with an absent config: default enforce, shipped default policy."""

    def setUp(self) -> None:
        """Chdir into the repo, route trace rows to a temp dir and use no config file."""
        super().setUp()
        self.cfg = self.dir.parent / "workflow.config.yaml"
        old = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, old)
        env = mock.patch.dict(
            os.environ,
            {
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
                "CODERAILS_PUBLICATION_SESSION_ID": "s",
                "CODEX_SESSION_ID": "",
                "CODEX_THREAD_ID": "",
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def commit(self, name: str, text: str = "x\n") -> None:
        """Add and commit one regular file."""
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", name)

    def gate(self, config_text: str | None = None, **kwargs: str) -> None:
        """Run the gate against the given config text (None = no config file)."""
        if config_text is not None:
            self.cfg.write_text(config_text)
        found = str(self.cfg) if config_text is not None else ""
        with mock.patch.object(manifest_policy, "config_path", return_value=found):
            manifest_policy.gate(**kwargs)

    def refusal(self, config_text: str | None = None, **kwargs: str) -> str:
        """Return the text of the WorkflowError the gate raises."""
        with self.assertRaises(git.WorkflowError) as caught:
            self.gate(config_text, **kwargs)
        return str(caught.exception)

    def test_secret_path_refused_by_default(self) -> None:
        """No config at all: a secret-shaped file is refused with denied_path."""
        self.commit(SECRET, "k=v\n")
        self.assertEqual(self.refusal(), "diff_manifest:denied_path")

    def test_review_policy_cannot_remove_required_passes_in_its_own_pr(self) -> None:
        """A PR cannot replace the required-review policy with an empty one."""
        git_cmd(self.dir, "checkout", "-q", "main")
        self.commit("policy/review_policy.json", '{"always":["review-pr"],"rules":[]}\n')
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        git_cmd(self.dir, "checkout", "-qB", "feature/x", "origin/main")
        self.commit("policy/review_policy.json", '{"always":[],"rules":[]}\n')
        self.assertEqual(self.refusal(), "diff_manifest:denied_path")

    def test_first_review_policy_install_is_allowed(self) -> None:
        """The release that first adds the policy can pass the diff gate."""
        self.commit("policy/review_policy.json", '{"always":["review-pr"],"rules":[]}\n')
        self.gate()

    def test_protected_policy_deletion_refused_by_default(self) -> None:
        """Deleting a policy file from the real diff is still denied."""
        git_cmd(self.dir, "checkout", "-q", "main")
        policy = self.dir / "policy/diff-policy.default.json"
        policy.parent.mkdir()
        policy.write_text("{}\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "base policy")
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        git_cmd(self.dir, "checkout", "-qB", "feature/x", "origin/main")
        policy.unlink()
        git_cmd(self.dir, "add", "-u")
        git_cmd(self.dir, "commit", "-qm", "remove policy")
        self.assertEqual(self.refusal(), "diff_manifest:denied_path")

    def test_pr_diff_uses_target_base_not_main(self) -> None:
        """A release-targeted PR includes a denied path already present on newer main."""
        release = git_cmd(self.dir, "rev-parse", "origin/main").strip()
        self.commit(SECRET, "k=v\n")
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.commit("docs.md", "doc\n")
        head = git_cmd(self.dir, "rev-parse", "HEAD").strip()

        def field(_number: str, name: str, fallback: str = "") -> str:
            return {"baseRefOid": release, "headRefOid": head}.get(name, fallback)

        with (
            mock.patch.object(git, "pr_field", side_effect=field),
            mock.patch.object(manifest_policy, "config_path", return_value=""),
        ):
            codes = [item["code"] for item in manifest_policy.violations("7", head=head)]
        self.assertIn("diff_manifest:denied_path", codes)

    def test_symlink_refused_by_default(self) -> None:
        """No config at all: a symlink is refused with special_file_type."""
        (self.dir / "link").symlink_to("README.md")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "link")
        self.assertEqual(self.refusal(), "diff_manifest:special_file_type")

    def test_clean_docs_diff_passes_default(self) -> None:
        """Negative control: the default is not a blanket block."""
        self.commit("docs/guide.md", "hello\n")
        self.gate()

    def test_graph_publication_without_unit_refuses(self) -> None:
        """A session-owned graph unit cannot publish without its manifest binding."""
        self.commit("docs/guide.md", "hello\n")
        session = "manifest-test-session"
        graph_progress(self.dir, self.loop, ["docs/**"], unit="1", session=session)
        with mock.patch.dict(
            os.environ,
            {
                "CLAUDE_CODE_SESSION_ID": session,
                "CODERAILS_PUBLICATION_SESSION_ID": session,
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            },
        ):
            self.assertEqual(self.refusal(), "diff_manifest:manifest_unreadable")
        with mock.patch.dict(
            os.environ,
            {
                "CLAUDE_CODE_SESSION_ID": session,
                "CODERAILS_PUBLICATION_SESSION_ID": session,
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop / "other-root"),
                "CODERAILS_AGENTIC_LOOP_DIR": str(self.loop),
            },
        ):
            self.gate()

    def test_off_passes_the_violating_diff(self) -> None:
        """Negative control: diff_manifest off proves the refusal comes from the gate."""
        self.commit(SECRET, "k=v\n")
        self.gate("diff_manifest: off\n")

    def test_advisory_only_warns(self) -> None:
        """Negative control: advisory (the old default) lets the same diff through, with a warning row."""
        self.commit(SECRET, "k=v\n")
        self.gate("diff_manifest: advisory\n")
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        self.assertIn(("warned", "denied_path"), [(r["outcome"], r["reason_code"]) for r in rows])

    def test_invalid_mode_is_rejected(self) -> None:
        """An unknown mode is refused by the strict config reader."""
        self.commit(SECRET, "k=v\n")
        self.assertEqual(self.refusal("diff_manifest: sometimes\n"), "config_rejected")
        rows = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        self.assertIn("config_rejected", [r["reason_code"] for r in rows])

    def test_missing_policy_file_refuses(self) -> None:
        """Negative control: a policy file that cannot be read refuses, never silently passes."""
        self.commit("docs/guide.md")
        self.assertEqual(
            self.refusal(f"diff_manifest_policy: {self.dir}/nope.json\n"), "diff_manifest:manifest_unreadable"
        )

    def test_internal_error_enforce_refuses_advisory_opens(self) -> None:
        """Negative control: an unexpected exception refuses under enforce and fails open under advisory."""
        self.commit("docs/guide.md")
        with mock.patch.object(manifest_policy, "diff_changes", side_effect=RuntimeError("boom")):
            self.assertEqual(self.refusal(), "diff_manifest:manifest_internal_error")
            self.gate("diff_manifest: advisory\n")

    def test_docs_sync_policy_refuses_script_and_rename(self) -> None:
        """The shipped docs-sync policy refuses a script edit and a rename of a script into a .md."""
        config_text = f"diff_manifest_policy: {REPO}/policy/docs-sync.policy.json\n"
        self.commit("scripts/x.py")
        self.assertEqual(self.refusal(config_text), "diff_manifest:docs_sync_deny")
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        git_cmd(self.dir, "mv", "scripts/gate.sh", "evil.md")
        git_cmd(self.dir, "commit", "-qam", "evil")
        with self.assertRaises(git.WorkflowError) as caught:
            self.gate(config_text)
        self.assertEqual(str(caught.exception), "diff_manifest:docs_sync_deny")
        self.assertIn("scripts/gate.sh", [v["detail"] for v in self.codes(config_text)])

    def test_unit_manifest_refuses_outside_file(self) -> None:
        """--unit/--progress: a file outside the unit's manifest is out_of_manifest."""
        self.commit("README.md", "changed\n")
        progress = graph_progress(self.dir, self.loop, ["src/**"])
        self.assertEqual(self.refusal(unit="2", progress=str(progress)), "diff_manifest:out_of_manifest")
        progress = graph_progress(self.dir, self.loop, ["**/*.md"], session="s2")
        with mock.patch.dict(os.environ, {"CODERAILS_PUBLICATION_SESSION_ID": "s2"}):
            self.gate(unit="2", progress=str(progress))

    def test_retro_policy_refuses_second_path_and_added_file(self) -> None:
        """The shipped retro-promotion policy trips too_many_paths and status_not_allowed."""
        config_text = f"diff_manifest_policy: {REPO}/policy/retro-promotion.policy.json\n"
        target = "skills/agentic-loop/learned-failure-modes.md"
        self.commit(target)
        self.assertIn("status_not_allowed", [v["code"] for v in self.codes(config_text)])
        git_cmd(self.dir, "reset", "-q", "--hard", "origin/main")
        self.commit(target)
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        (self.dir / target).write_text("edited\n")
        (self.dir / "extra.md").write_text("x\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "two")
        self.assertIn("too_many_paths", [v["code"] for v in self.codes(config_text)])

    def codes(self, config_text: str) -> list[dict[str, str]]:
        """Violations for the given config text, with the config file patched in."""
        self.cfg.write_text(config_text)
        with mock.patch.object(manifest_policy, "config_path", return_value=str(self.cfg)):
            return [{"code": v["code"].split(":", 1)[1], "detail": v["detail"]} for v in manifest_policy.violations()]


if __name__ == "__main__":
    unittest.main()
