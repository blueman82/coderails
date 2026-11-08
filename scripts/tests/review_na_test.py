"""Immutable standalone-wiki scope at the parser, paired reader and publication boundary."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import publication_gate, review_na, review_passes  # noqa: E402
from scripts.tests.review_passes_test import OTHER, SHA, body, entry, found  # noqa: E402


def na_summary(scope: dict[str, object]) -> str:
    """Render a specialist's scope, independently of the posting implementation."""
    return "## Not applicable\n\n```json\n" + json.dumps(scope) + "\n```\n"


class WikiNaTests(unittest.TestCase):
    """Real immutable Git facts must constrain the new disposition at its consumers."""

    def setUp(self) -> None:
        """Create a wiki with an unchanged consumer and four page operation types."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        previous = Path.cwd()
        os.chdir(self.directory)
        self.addCleanup(os.chdir, previous)
        self.git("init", "-q", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/o/wiki.git")
        for path, text in {
            "hooks/edit.md": "old\n",
            "hooks/delete.md": "delete\n",
            "commands/from.md": "rename\n",
            ".obsidian/plugins/view/main.js": "// displays prose, no execution\n",
        }.items():
            target = self.directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.live_base = self.base
        self.git("checkout", "-qb", "pages")
        (self.directory / "hooks/edit.md").write_text("new\n")
        (self.directory / "hooks/delete.md").unlink()
        (self.directory / "commands/from.md").rename(self.directory / "commands/to.md")
        (self.directory / "hooks/add.md").write_text("add\n")
        self.git("add", ".")
        self.git("commit", "-qm", "pages")
        self.head = self.git("rev-parse", "HEAD").strip()
        real_run = git.run

        def remote(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            """Replace authenticated remote reads only; all Git object reads remain real."""
            if arguments[:2] != ("gh", "api"):
                return real_run(*arguments, check=check)
            if arguments[2] == "repos/o/wiki/pulls/7":
                out = json.dumps({"repository": "o/wiki", "head_sha": self.head, "base_ref": "main"})
            elif arguments[2] == "repos/o/wiki/git/ref/heads/main":
                out = self.live_base
            else:
                raise AssertionError(arguments)
            return subprocess.CompletedProcess(arguments, 0, out + "\n", "")

        self.addCleanup(mock.patch.stopall)
        mock.patch.object(git, "run", side_effect=remote).start()

    def git(self, *arguments: str) -> str:
        """Use an isolated identity and disable any inherited hooks for inert fixture commits."""
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *arguments], env=env, check=True, capture_output=True, text=True
        ).stdout

    def scope(self) -> dict[str, Any]:
        """Use the real preparation output, then supply the independent consumer assessment."""
        facts = review_na.prepare("7", self.head)
        return {
            "boundary": "standalone_wiki_prose_v3",
            "binding": facts["binding"],
            "repository_purpose": "Standalone prose wiki.",
            "consumer_scope": {
                "complete": True,
                "effect_state": "effect_free",
                "references": [
                    {
                        "paths": [".obsidian/plugins/view/main.js"],
                        "base_change_assessment": None,
                        "effect_state": "effect_free",
                        "assessment": "Both ordinary blob modes and code display prose only.",
                    }
                ],
                "assessment": "Names, existence, deletion, permissions and instructions cannot execute prose.",
                "unresolved": [],
            },
        }

    def test_name_aware_scope_round_trips_through_paired_reader(self) -> None:
        """N/A survives its real parser and companion reader but cannot replace general review."""
        scope = self.scope()
        text = na_summary(scope)
        review_passes.validate_summary_text(text, name="security-review")
        self.assertEqual(review_passes.verdict_from_summary(text, name="security-review"), "not_applicable")
        for name in ("review-pr", "deploy-safety"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                review_passes.validate_summary_text(text, name=name)
        passes: list[dict[str, object]] = [
            entry("review-pr"),
            {
                "name": "security-review",
                "verdict": "not_applicable",
                "blocking": False,
                "summary_sha256": review_passes.summary_sha256(text),
            },
        ]
        posted = body(passes, sha=self.head, texts={"security-review": text})
        companion = body(None, sha=self.head)
        with mock.patch.object(git, "trusted_comment_bodies", return_value=[posted, companion]):
            found_scope = git.review_passes_for_pr("7", self.head).passes
        self.assertIsNotNone(found_scope)
        assert found_scope is not None
        self.assertEqual(found_scope[1]["scope"], scope)

    def test_scope_reaches_the_real_publication_check(self) -> None:
        """An eligible N/A passes; stale affected entries and optional invalid N/A refuse."""
        scope = self.scope()
        reply = found(
            [
                entry("review-pr"),
                {"name": "security-review", "verdict": "not_applicable", "blocking": False, "scope": scope},
            ]
        )
        with (
            mock.patch.object(git, "gate_review_summary_for_pr", return_value=(0, "")),
            mock.patch.object(git, "review_passes_for_pr", return_value=reply),
            mock.patch.object(git, "pr_field", return_value=self.base),
            mock.patch.object(publication_gate, "load_config", return_value=({}, [])),
        ):
            self.assertEqual(publication_gate.review_passes_check("7", self.head, "", ""), [])
            self.git("checkout", "-q", "main")
            (self.directory / "hooks/edit.md").chmod(0o755)
            self.git("add", ".")
            self.git("commit", "-qm", "base mode changed")
            self.live_base = self.git("rev-parse", "HEAD").strip()
            result = publication_gate.review_passes_check("7", self.head, "", "")
            self.assertEqual(result[0]["code"], "required_review_not_applicable_invalid:security-review")
            self.assertIn("affected", result[0]["detail"])

    def test_exact_json_and_complete_inventory_are_required(self) -> None:
        """Unknown and duplicate fields, extra prose and blocking N/A never become a parsed pass."""
        scope = self.scope()
        text = na_summary(scope)
        for invalid in (
            text + "extra\n",
            text.replace('"boundary":', '"extra": 1, "boundary":'),
            text.replace('"complete": true', '"complete": true, "complete": true'),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                review_passes.validate_summary_text(invalid, name="security-review")
        facts = review_na.prepare("7", self.head)
        self.assertEqual([row["status"] for row in facts["inventory"]], ["A", "R", "D", "M"])
        old = self.git("rev-parse", self.base + ":hooks/edit.md").strip()
        new = self.git("rev-parse", self.head + ":hooks/edit.md").strip()
        self.assertIn(
            {
                "status": "M",
                "old": {"path": "hooks/edit.md", "mode": "100644", "blob": old},
                "new": {"path": "hooks/edit.md", "mode": "100644", "blob": new},
            },
            facts["inventory"],
        )

    def test_live_base_and_consumer_changes_require_new_facts(self) -> None:
        """A base-only page change is forbidden even after rebinding; consumer changes need assessment."""
        scope = self.scope()
        self.git("checkout", "-q", "main")
        consumer = self.directory / ".obsidian/plugins/view/main.js"
        consumer.write_text("// newer prose display\n")
        self.git("add", ".")
        self.git("commit", "-qm", "consumer changed on base")
        self.live_base = self.git("rev-parse", "HEAD").strip()
        fresh = self.scope()
        with self.assertRaisesRegex(ValueError, "consumer"):
            review_na.validate(fresh, "7", self.head)
        # Literal edits model a reviewer who read the new base consumer, not a writer waiver.
        reference = fresh["consumer_scope"]["references"][0]
        reference["base_change_assessment"] = "Base change only changes display text; page operations remain inert."
        review_na.validate(fresh, "7", self.head)
        with self.assertRaisesRegex(ValueError, "stale"):
            review_na.validate(scope, "7", self.head)
        (self.directory / "hooks/add.md").write_text("base now contains added endpoint\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base adds page")
        self.live_base = self.git("rev-parse", "HEAD").strip()
        with self.assertRaisesRegex(ValueError, "affected"):
            review_na.prepare("7", self.head)

    def test_plugins_controls_modes_and_missing_context_are_ineligible(self) -> None:
        """Whole-tree plugin markers and either forbidden rename endpoint deny scope preparation."""
        scope = self.scope()
        bad = copy.deepcopy(scope)
        bad["consumer_scope"]["complete"] = False
        with self.assertRaises(ValueError):
            review_na.validate(bad, "7", self.head)
        self.git("checkout", "-q", "pages")
        (self.directory / ".codex-plugin").mkdir()
        (self.directory / ".codex-plugin/plugin.json").write_text("{}")
        self.git("add", ".")
        self.git("commit", "-qm", "plugin marker")
        self.head = self.git("rev-parse", "HEAD").strip()
        with self.assertRaisesRegex(ValueError, "plugin"):
            review_na.prepare("7", self.head)

    def test_either_rename_endpoint_controls_and_endpoint_modes_refuse(self) -> None:
        """A prohibited source stays prohibited after deletion, rename, chmod or a symlink conversion."""
        for path in (
            "AGENTS.md",
            "nested/CLAUDE.md",
            "skills/x/SKILL.md",
            "scripts/prose.md",
            "nested/.CODEX/page.md",
            "agents/page.md",
        ):
            for reverse in (False, True):
                with self.subTest(path=path, reverse=reverse):
                    self.git("checkout", "-q", "--detach", self.base)
                    target = self.directory / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("unique rename content\n")
                    self.git("add", ".")
                    self.git("commit", "-qm", "prohibited page baseline")
                    source = self.git("rev-parse", "HEAD").strip()
                    safe = self.directory / "hooks/renamed.md"
                    if reverse:
                        target.unlink()
                        safe.write_text("unique rename content\n")
                        self.git("add", ".")
                        self.git("commit", "-qm", "safe page baseline")
                        source = self.git("rev-parse", "HEAD").strip()
                        safe.rename(target)
                    else:
                        target.rename(safe)
                    self.git("add", ".")
                    self.git("commit", "-qm", "rename endpoint")
                    self.live_base = source
                    self.head = self.git("rev-parse", "HEAD").strip()
                    with self.assertRaisesRegex(ValueError, "ineligible"):
                        review_na.prepare("7", self.head)
        for operation in ("executable", "symlink", "delete_executable"):
            with self.subTest(operation=operation):
                self.git("checkout", "-q", "--detach", self.base)
                target = self.directory / "hooks/edit.md"
                if operation == "delete_executable":
                    target.chmod(0o755)
                    self.git("add", ".")
                    self.git("commit", "-qm", "executable baseline")
                self.live_base = self.git("rev-parse", "HEAD").strip()
                if operation == "executable":
                    target.chmod(0o755)
                elif operation == "symlink":
                    target.unlink()
                    target.symlink_to("../commands/from.md")
                else:
                    target.unlink()
                self.git("add", ".")
                self.git("commit", "-qm", "wrong endpoint mode")
                self.head = self.git("rev-parse", "HEAD").strip()
                with self.assertRaises(ValueError):
                    review_na.prepare("7", self.head)

    def test_both_rename_names_and_base_deletion_block_rebound_scope(self) -> None:
        """Base-only entries at a rename destination or source cannot evade authored-diff checks."""
        head = self.head
        for path, operation in (
            ("commands/from.md", "delete"),
            ("commands/to.md", "add"),
            ("hooks/delete.md", "change"),
        ):
            with self.subTest(path=path):
                self.git("checkout", "-q", "--detach", self.base)
                target = self.directory / path
                if operation == "delete":
                    target.unlink()
                else:
                    target.write_text("base-only entry\n")
                self.git("add", ".")
                self.git("commit", "-qm", "base drift")
                self.live_base = self.git("rev-parse", "HEAD").strip()
                with self.assertRaisesRegex(ValueError, "affected"):
                    review_na.prepare("7", head)

    def test_raw_parser_refuses_truncation_copies_and_unknown_status(self) -> None:
        """An incomplete or unsupported raw inventory never reaches an eligible artifact."""
        for raw in (
            "",
            f":100644 100644 {SHA} {OTHER} R100\0hooks/a.md\0",
            f":100644 100644 {SHA} {OTHER} C100\0hooks/a.md\0hooks/b.md\0",
            f":100644 100644 {SHA} {OTHER} X\0hooks/a.md\0",
            f":100644 100644 {SHA} {OTHER} M\0hooks/a.md\0garbage\0",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                review_na.inventory(raw)

    def test_ambiguous_consumer_paths_and_git_components_are_malformed(self) -> None:
        """Case aliases cannot describe two independent consumers on supported case-insensitive checkouts."""
        scope = self.scope()
        reference = scope["consumer_scope"]["references"][0]
        scope["consumer_scope"]["references"].append({**reference, "paths": [reference["paths"][0].upper()]})
        with self.assertRaises(ValueError):
            review_na.validate_schema(scope)
        scope["consumer_scope"]["references"] = [{**reference, "paths": ["nested/.GIT/config"]}]
        with self.assertRaises(ValueError):
            review_na.validate_schema(scope)

    def test_modified_rename_preserves_both_complete_endpoints(self) -> None:
        """A real scored rename remains eligible when its ordinary Markdown content also changes."""
        self.git("checkout", "-q", "--detach", self.base)
        source = self.directory / "commands/more.md"
        source.write_text("".join(f"Prose line {index}\n" for index in range(20)))
        self.git("add", ".")
        self.git("commit", "-qm", "rename baseline")
        self.live_base = self.git("rev-parse", "HEAD").strip()
        target = self.directory / "commands/renamed.md"
        source.rename(target)
        target.write_text(target.read_text().replace("Prose line 0", "Changed prose"))
        self.git("add", ".")
        self.git("commit", "-qm", "scored rename")
        self.head = self.git("rev-parse", "HEAD").strip()
        try:
            row = review_na.prepare("7", self.head)["inventory"][0]
        except ValueError as error:
            self.fail(str(error))
        self.assertEqual(
            (row["status"], row["old"]["path"], row["new"]["path"]), ("R", "commands/more.md", "commands/renamed.md")
        )

    def test_submodule_ignore_config_cannot_hide_mixed_gitlink_changes(self) -> None:
        """Added, changed and deleted gitlinks stay visible despite global and per-submodule ignore settings."""
        for operation in ("add", "change", "delete"):
            with self.subTest(operation=operation):
                self.git("checkout", "-q", "--detach", self.base)
                if operation != "add":
                    self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},runtime")
                    self.git("commit", "-qm", "gitlink baseline")
                self.live_base = self.git("rev-parse", "HEAD").strip()
                (self.directory / "hooks/edit.md").write_text("changed prose\n")
                self.git("add", "hooks/edit.md")
                if operation == "delete":
                    self.git("update-index", "--force-remove", "runtime")
                else:
                    self.git("update-index", "--add", "--cacheinfo", f"160000,{self.head},runtime")
                self.git("commit", "-qm", "mixed prose and gitlink")
                self.head = self.git("rev-parse", "HEAD").strip()
                self.git("config", "diff.ignoreSubmodules", "all")
                self.git("config", "submodule.runtime.ignore", "all")
                with self.assertRaises(ValueError):
                    review_na.prepare("7", self.head)

    def test_relative_diff_config_cannot_hide_changes_outside_the_working_directory(self) -> None:
        """Immutable inventory paths and scope remain rooted at the repository from a nested working directory."""
        pure = self.head
        (self.directory / "runtime.py").write_text("pass\n")
        self.git("add", "runtime.py")
        self.git("commit", "-qm", "mixed prose and runtime")
        mixed = self.git("rev-parse", "HEAD").strip()
        self.git("config", "diff.relative", "true")
        os.chdir(self.directory / "hooks")
        self.head = pure
        facts = review_na.prepare("7", pure)
        self.assertIn("commands/from.md", [row["old"]["path"] for row in facts["inventory"] if row["old"]])
        self.head = mixed
        with self.assertRaises(ValueError):
            review_na.prepare("7", mixed)


if __name__ == "__main__":
    unittest.main()
