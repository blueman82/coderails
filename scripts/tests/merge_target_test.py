"""merge_target: which PR a merge command really names (flag values skipped, URL and branch forms, -R refused)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_policy, merge_target  # noqa: E402


class ParseTests(unittest.TestCase):
    """parse() returns (target, unit, progress); target is "" for none and "?" for ambiguous."""

    def target(self, segment: str) -> str:
        """The target of one segment."""
        return merge_target.parse(segment)[0]

    def test_flag_values_are_not_the_target(self) -> None:
        """Negative control for the first-digit bug: `--body 1 42` names PR 42."""
        self.assertEqual(self.target("gh pr merge --body 1 42"), "42")
        self.assertEqual(self.target("gh pr merge --body=1 42 --squash"), "42")
        self.assertEqual(self.target("gh pr merge 42 --subject 9"), "42")
        self.assertEqual(self.target("gh pr merge --match-head-commit 3 42"), "42")

    def test_url_and_branch_forms(self) -> None:
        """A URL or a branch name is the target, not an absent one."""
        self.assertEqual(self.target("gh pr merge https://github.com/o/r/pull/42"), "https://github.com/o/r/pull/42")
        self.assertEqual(self.target("gh pr merge feat-b --merge"), "feat-b")

    def test_only_unconsumed_noop_options_are_harmless(self) -> None:
        """One arity table governs quoted/equals-form values and genuine no-op flags."""
        for value in ("--help", "--dry-run"):
            for option in ("--body", "-b", "--subject", "--body-file", "--match-head-commit", "--repo", "-R"):
                for argument in (f"{option} '{value}'", f"{option}={value}"):
                    with self.subTest(argument=argument):
                        self.assertFalse(merge_target.has_noop_option(f"gh pr merge 42 {argument}"))
            self.assertTrue(merge_target.has_noop_option(f"gh pr merge --body 'ordinary text' 42 {value}"))
            self.assertTrue(merge_target.has_noop_option(f"gh pr merge 42 '{value}'"))
        for command in ("gh pr merge --body", "gh pr merge --body '--help", "gh pr merge --body 'text --help'"):
            self.assertFalse(merge_target.has_noop_option(command))

    def test_no_target_and_api_form(self) -> None:
        """No positional means the current branch; the api form carries the number in the path."""
        self.assertEqual(self.target("gh pr merge --merge"), "")
        self.assertEqual(self.target("gh api repos/o/r/pulls/9/merge -X PUT"), "https://github.com/o/r/pull/9")
        self.assertEqual(self.target("gh api -X PUT repos/o/r/pulls/9/merge"), "https://github.com/o/r/pull/9")

    def test_endpoint_text_in_body_is_not_a_target(self) -> None:
        """Only the API endpoint argument selects an API merge target."""
        self.assertEqual(self.target("gh pr merge --body '/pulls/1/merge' 42"), "42")
        self.assertEqual(self.target("gh api repos/x/y/pulls/9/merge -X PUT"), "https://github.com/x/y/pull/9")
        self.assertEqual(
            self.target("gh api -f note=repos/x/y/pulls/9/merge repos/x/y/issues/9"), merge_target.AMBIGUOUS
        )

    def test_ambiguous_is_marked(self) -> None:
        """-R/--repo and two positionals cannot be resolved against the local repo."""
        self.assertEqual(self.target("gh pr merge --repo other/repo 12"), merge_target.AMBIGUOUS)
        self.assertEqual(self.target("gh pr merge -R other/repo 12"), merge_target.AMBIGUOUS)
        self.assertEqual(self.target("gh pr merge 1 2"), merge_target.AMBIGUOUS)
        self.assertEqual(self.target("gh pr merge 'unclosed"), merge_target.AMBIGUOUS)

    def test_repository_override_forms_refuse(self) -> None:
        """Attached and separate repository options refuse before or after the target."""
        for option in ("-Rother/repo", "-R other/repo", "--repo=other/repo", "--repo other/repo"):
            for command in (f"gh pr merge {option} 42", f"gh pr merge 42 {option}", f"gh {option} pr merge 42"):
                with self.subTest(command=command):
                    self.assertEqual(self.target(command), merge_target.AMBIGUOUS)
        self.assertEqual(self.target("gh pr merge --body '-Rother/repo' 42 --squash"), "42")

    def test_merge_script_with_unit_flags(self) -> None:
        """merge.py: --unit/--progress are stripped before the number is read, and returned."""
        got = merge_target.parse("python3 scripts/merge.py --unit 2 --progress p.json 5")
        self.assertEqual(got, ("5", "2", "p.json"))
        self.assertEqual(merge_target.parse("python3 scripts/merge.py auto"), ("", "", ""))

    def test_merge_script_expected_head_value_is_not_a_second_target(self) -> None:
        """The pinned head is an option value; the hook still resolves the named PR."""
        sha = "a" * 40
        self.assertEqual(merge_target.parse(f"python3 scripts/merge.py 516 --expected-head {sha}"), ("516", "", ""))
        self.assertEqual(merge_target.parse(f"python3 scripts/merge.py --expected-head={sha} 516"), ("516", "", ""))
        self.assertEqual(merge_target.parse("python3 scripts/merge.py 516 --expected-head 517"), ("516", "", ""))

    def test_unit_flags_inline_missing_and_duplicates(self) -> None:
        """Wrapper flags support equals syntax and refuse missing or ambiguous values."""
        self.assertEqual(manifest_policy.unit_flags(["42", "--unit=2", "--progress=p.json"]), (["42"], "2", "p.json"))
        for flags in (
            ["--unit"],
            ["--progress="],
            ["--unit", "--progress", "p.json"],
            ["--unit", "2", "--unit", "3", "--progress", "p.json"],
        ):
            with self.subTest(flags=flags), self.assertRaises(git.WorkflowError):
                manifest_policy.unit_flags(flags)

    def test_script_scope_flags_cannot_silently_disappear(self) -> None:
        """An invalid scope option makes the hook target unresolvable."""
        for flags in ("--unit", "--progress=", "--unit 2 --unit 3 --progress p.json"):
            with self.subTest(flags=flags):
                self.assertEqual(merge_target.parse(f"python3 scripts/merge.py 42 {flags}")[0], merge_target.AMBIGUOUS)


class ResolveTests(unittest.TestCase):
    """resolve() turns a target into a PR number of THIS repo, or empty text."""

    def test_number_url_branch(self) -> None:
        """Digits pass through; a same-repo URL and a branch go through gh; no target is the current branch."""

        def number(name: str) -> str:
            return "3" if name == "cur" else "7"

        with (
            mock.patch.object(git, "repo", return_value="o/r"),
            mock.patch.object(git, "pr_num", side_effect=number) as lookup,
            mock.patch.object(git, "branch", return_value="cur"),
        ):
            self.assertEqual(merge_target.resolve("42"), "42")
            self.assertEqual(merge_target.resolve("https://github.com/o/r/pull/7"), "7")
            self.assertEqual(merge_target.resolve("feat-b"), "7")
            self.assertEqual(lookup.call_args.args, ("feat-b",))
            self.assertEqual(merge_target.resolve(""), "3")

    def test_unresolvable_is_empty(self) -> None:
        """Ambiguous, other-repo URL and a branch gh cannot find never fall back to the current branch's PR."""
        with (
            mock.patch.object(git, "repo", return_value="o/r"),
            mock.patch.object(git, "pr_field", return_value=""),
            mock.patch.object(git, "pr_num", return_value=""),
        ):
            self.assertEqual(merge_target.resolve(merge_target.AMBIGUOUS), "")
            self.assertEqual(merge_target.resolve("https://github.com/x/y/pull/7"), "")
            self.assertEqual(merge_target.resolve("nope"), "")
            self.assertEqual(merge_target.resolve("https://example.com/o/r/pull/7"), "")


if __name__ == "__main__":
    unittest.main()
