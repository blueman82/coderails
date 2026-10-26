"""Required-reviewer policy, the passes line, and the review_passes publication check (merge.py, Claude direct path)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.lib import pr_merge_gate  # noqa: E402
from scripts import merge  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_policy, publication_gate, review_artifact, review_passes  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
CLEAN = "## No findings\n"
CRITICAL = "## Critical\n- injection in hooks/x.py\n\n## Important\nNone\n\n## Suggestions\nNone\n"
HOOKS = [("M", ["hooks/x.py"])]
DOCS = [("M", ["docs/a.md"])]
# What merge.py did before this change: any v1 marker satisfied the gate, whatever the diff touched.
OLD_BEHAVIOUR_REQUIRED_NAMES: list[str] = []


def entry(name: str, text: str = CLEAN, **over: object) -> dict[str, object]:
    """A passes[] entry the way post_review.py post derives it."""
    verdict = review_passes.verdict_from_summary(text)
    base: dict[str, object] = {
        "name": name,
        "verdict": verdict,
        "blocking": verdict == "fail",
        "summary_sha256": review_passes.summary_sha256(text),
    }
    return {**base, **over}


def body(
    passes: list[dict[str, object]] | None, sha: str = SHA, pr: str = "7", texts: dict[str, str] | None = None
) -> str:
    """A posted artifact body: v1 marker, optional passes line, then the summaries the passes were derived from."""
    lines = [review_artifact.marker(pr, sha)]
    if passes is not None:
        lines.append(review_passes.render(sha, passes))
    names = ["review-pr"] + [str(p["name"]) for p in passes or [] if p["name"] != "review-pr"]
    given = texts or {}
    return "\n".join(lines + [review_passes.tail([(n, given.get(n, CLEAN)) for n in names])])


class PolicyTests(unittest.TestCase):
    """load_policy and required: which passes a diff needs."""

    def setUp(self) -> None:
        """Load the shipped policy."""
        self.policy = review_passes.load_policy()

    def test_docs_only_needs_only_review_pr(self) -> None:
        """A docs-only diff requires review-pr alone."""
        self.assertEqual(review_passes.required(DOCS, self.policy), ["review-pr"])

    def test_security_paths_require_security_review(self) -> None:
        """Every listed security path pulls in security-review, once."""
        for path in (
            "hooks/x.py",
            "scripts/a/b.py",
            "install.py",
            "uninstall.py",
            ".claude-plugin/plugin.json",
            "packages/codex/hooks/scripts/h.py",
            "packages/codex/scripts/lib/z.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(review_passes.required([("M", [path])], self.policy), ["review-pr", "security-review"])

    def test_control_files_require_security_review(self) -> None:
        """The policy and the other control files cannot be changed on review-pr alone."""
        for path in (
            "policy/review_policy.json",
            "packages/codex/policy/review_policy.json",
            "capabilities/profiles.json",
            "packages/codex/capabilities/profiles.json",
            "agents/security-reviewer.md",
            "packages/codex/agents/x.toml",
            "commands/post-review.md",
            "packages/codex/skills/post-review/SKILL.md",
            "packages/codex/skills/merge/SKILL.md",
            "AGENTS.md",
            "workflow.config.yaml",
            ".coderails/workflow.config.yaml",
        ):
            with self.subTest(path=path):
                self.assertIn("security-review", review_passes.required([("M", [path])], self.policy))

    def test_deploy_paths_require_deploy_safety(self) -> None:
        """Deploy paths pull in deploy-safety; scripts/installer also needs security-review."""
        for path in ("launchd/a.plist", ".github/workflows/ci.yml", "skills/dashboard/runner/x.ts"):
            with self.subTest(path=path):
                self.assertEqual(review_passes.required([("M", [path])], self.policy), ["review-pr", "deploy-safety"])
        both = review_passes.required([("M", ["scripts/installer/x.py"])], self.policy)
        self.assertEqual(both, ["review-pr", "security-review", "deploy-safety"])

    def test_rename_source_counts(self) -> None:
        """A rename out of hooks/ still needs the security review."""
        got = review_passes.required([("R100", ["hooks/a.py", "docs/a.py"])], self.policy)
        self.assertIn("security-review", got)

    def test_missing_policy_is_unreadable(self) -> None:
        """Negative control: a deleted or torn policy raises review_policy_unreadable (fail closed)."""
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "none.json"
            with self.assertRaises(ValueError) as caught:
                review_passes.load_policy(missing)
            self.assertEqual(str(caught.exception), "review_policy_unreadable")
            torn = Path(tmp) / "torn.json"
            torn.write_text("{")
            with self.assertRaises(ValueError):
                review_passes.load_policy(torn)
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"always": ["review-pr"], "rules": [{"pass": "x", "paths": "hooks/**"}]}))
            with self.assertRaises(ValueError):
                review_passes.load_policy(bad)


class LineTests(unittest.TestCase):
    """render, parse and verdict_from_summary."""

    def test_round_trip(self) -> None:
        """A rendered line parses back to the same entries."""
        passes = [entry("review-pr"), entry("security-review")]
        self.assertEqual(review_passes.parse(body(passes), "7", SHA), passes)

    def test_no_line_is_empty_passes(self) -> None:
        """A v1 artifact without a passes line counts as passes=[]."""
        self.assertEqual(review_passes.parse(body(None), "7", SHA), [])

    def test_present_line_must_bind_review_pr_verdict(self) -> None:
        """A specialist pass cannot hide a Critical finding in the main review summary."""
        text = body([entry("security-review")], texts={"review-pr": CRITICAL})
        self.assertIsNone(review_passes.parse(text, "7", SHA))

    def test_line_bound_to_other_head_is_malformed(self) -> None:
        """A stale passes line cannot become an absent legacy line."""
        text = "\n".join([review_artifact.marker("7", SHA), review_passes.render(OTHER, [entry("security-review")])])
        self.assertIsNone(review_passes.parse(text, "7", SHA))

    def test_malformed_line_is_none(self) -> None:
        """A passes line that does not parse or validate is malformed (None), never silently empty."""
        marker = review_artifact.marker("7", SHA)
        prefix = "<!-- coderails-review-passes v1 "
        head = f'"head_sha": "{SHA}"'
        for bad in (
            prefix + "{ -->",
            prefix + "{" + head + ', "passes": "x"} -->',
            prefix + "{" + head + ', "passes": [{"name": "a"}]} -->',
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(review_passes.parse(marker + "\n" + bad, "7", SHA))

    def test_verdict_is_derived_from_text(self) -> None:
        """No findings or Critical None pass; any Critical bullet fails."""
        self.assertEqual(review_passes.verdict_from_summary(CLEAN), "pass")
        no_critical = CRITICAL.replace("- injection in hooks/x.py", "None")
        self.assertEqual(review_passes.verdict_from_summary(no_critical), "pass")
        self.assertEqual(review_passes.verdict_from_summary(CRITICAL), "fail")

    def test_prose_cannot_hide_a_critical_finding(self) -> None:
        """Any Critical line other than the single token None is a finding, whatever its bullet style."""
        for finding in ("* SQL injection", "1. RCE", "-\tbad", "  - indented", "prose finding"):
            with self.subTest(finding=finding):
                text = f"## Critical\nNone\n{finding}\n\n## Important\nNone\n\n## Suggestions\nNone\n"
                self.assertEqual(review_passes.verdict_from_summary(text), "fail")
        self.assertEqual(review_passes.verdict_from_summary("## Critical\n\n## Important\nNone\n"), "fail")

    def test_forged_pass_is_not_accepted(self) -> None:
        """The gate re-derives passes from the text: a forged hash, flipped verdict or missing section is malformed."""
        good = [entry("review-pr"), entry("security-review")]
        self.assertEqual(review_passes.parse(body(good), "7", SHA), good)
        forged = [entry("review-pr"), entry("security-review", summary_sha256="0" * 64)]
        self.assertIsNone(review_passes.parse(body(forged), "7", SHA))
        flipped = [entry("review-pr"), entry("security-review", CRITICAL, verdict="pass", blocking=False)]
        self.assertIsNone(review_passes.parse(body(flipped, texts={"security-review": CRITICAL}), "7", SHA))
        swapped = [entry("review-pr"), entry("security-review", CLEAN)]
        self.assertIsNone(review_passes.parse(body(swapped, texts={"security-review": CRITICAL}), "7", SHA))
        lines = body(good).splitlines()
        self.assertIsNone(review_passes.parse("\n".join(lines[:3]), "7", SHA))  # security-review section absent

    def test_first_line_is_still_the_v1_marker(self) -> None:
        """Compat: the dashboard and integrity-gate parsers only read the first line, which is unchanged."""
        first = body([entry("review-pr")]).splitlines()[0]
        self.assertEqual(first, f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->")
        self.assertTrue(review_artifact.matches_marker(first, "7", SHA))

    def test_ambiguous_and_duplicate_sections_are_malformed(self) -> None:
        """A matching hash cannot make conflicting summary grammar valid."""
        repeated = CRITICAL.replace("- injection in hooks/x.py", "None") + "\n" + CRITICAL
        for text in (CLEAN + CRITICAL, repeated, CLEAN + CLEAN):
            with self.subTest(text=text):
                passes = [entry("review-pr"), entry("security-review", text)]
                self.assertIsNone(review_passes.parse(body(passes, texts={"security-review": text}), "7", SHA))
        good = body([entry("review-pr"), entry("security-review")])
        duplicate = good + "\n<!-- coderails-review-pass security-review -->\n" + CLEAN
        self.assertIsNone(review_passes.parse(duplicate, "7", SHA))
        duplicates = body([entry("review-pr"), entry("security-review"), entry("security-review")])
        self.assertIsNone(review_passes.parse(duplicates, "7", SHA))
        self.assertIsNotNone(review_passes.parse(good, "7", SHA))


def found(passes: list[dict[str, object]] | None, status: int = 0, reason: str = "") -> git.ReviewPasses:
    """A review_passes_for_pr reply."""
    return git.ReviewPasses(status, None if passes is None else tuple(passes), reason)


class CheckTests(unittest.TestCase):
    """The publication-gate check: refusal codes, and the pre-change behaviour as a negative control."""

    def codes(self, reply: git.ReviewPasses, changes: manifest_policy.Changes | None = HOOKS) -> list[str]:
        """Run the check against a canned artifact and diff."""
        with (
            mock.patch.object(git, "review_passes_for_pr", return_value=reply),
            mock.patch.object(git, "pr_field", return_value="base-sha"),
            mock.patch.object(manifest_policy, "diff_changes", return_value=changes),
        ):
            return [v["code"] for v in publication_gate.review_passes_check("7", SHA, "", "")]

    def test_hooks_pr_with_only_review_pr_is_refused(self) -> None:
        """hooks/ diff and a review-pr pass alone: required_review_missing:security-review."""
        self.assertEqual(self.codes(found([entry("review-pr")])), ["required_review_missing:security-review"])

    def test_required_passes_use_the_pr_base(self) -> None:
        """A release PR needs security review for hooks/ changes already present on newer main."""

        def changes(_sha: str, _fetch: str, base: str = "") -> manifest_policy.Changes:
            return HOOKS if base == "release-sha" else DOCS

        with (
            mock.patch.object(git, "pr_field", return_value="release-sha"),
            mock.patch.object(git, "review_passes_for_pr", return_value=found([entry("review-pr")])),
            mock.patch.object(manifest_policy, "diff_changes", side_effect=changes),
        ):
            codes = [v["code"] for v in publication_gate.review_passes_check("7", SHA, "", "")]
        self.assertEqual(codes, ["required_review_missing:security-review"])

    def test_security_pass_present_proceeds(self) -> None:
        """Negative control: with the pass the same PR is accepted, so the refusal came from the policy."""
        self.assertEqual(self.codes(found([entry("review-pr"), entry("security-review")])), [])

    def test_failed_required_pass_is_refused(self) -> None:
        """A security pass whose summary has a Critical bullet is required_review_failed."""
        reply = found([entry("review-pr"), entry("security-review", CRITICAL)])
        self.assertEqual(self.codes(reply), ["required_review_failed:security-review"])

    def test_blocking_false_cannot_waive_a_required_pass(self) -> None:
        """Negative control: required comes from the policy; blocking:false on a failed pass still refuses."""
        reply = found([entry("review-pr"), entry("security-review", CRITICAL, blocking=False)])
        self.assertEqual(self.codes(reply), ["required_review_failed:security-review"])

    def test_docs_only_needs_review_pr_only(self) -> None:
        """A docs-only PR with the bare review-pr pass, or an old v1 artifact, is accepted."""
        self.assertEqual(self.codes(found([entry("review-pr")]), DOCS), [])
        self.assertEqual(self.codes(found([]), DOCS), [])

    def test_old_v1_artifact_on_hooks_pr_is_refused(self) -> None:
        """No passes line counts as passes=[]; a hooks/ PR is refused until re-posted (old behaviour: accepted)."""
        with mock.patch.object(git, "trusted_comment_bodies", return_value=[body(None)]):
            self.assertEqual(git.gate_review_summary_for_pr("7", SHA), (0, ""))  # the pre-change gate: accepted
            self.assertEqual(git.review_passes_for_pr("7", SHA), found([]))
        self.assertEqual(OLD_BEHAVIOUR_REQUIRED_NAMES, [])
        self.assertEqual(self.codes(found([])), ["required_review_missing:security-review"])

    def test_newest_matching_artifact_wins_and_stale_head_is_not_accepted(self) -> None:
        """A newer artifact replaces an older one; a body for another head is not an artifact at all."""
        bodies = [body([entry("review-pr"), entry("security-review")]), body([entry("review-pr")])]
        with mock.patch.object(git, "trusted_comment_bodies", return_value=bodies):
            self.assertEqual(git.review_passes_for_pr("7", SHA).passes, (entry("review-pr"),))
        with mock.patch.object(git, "trusted_comment_bodies", return_value=[body([entry("review-pr")], sha=OTHER)]):
            self.assertEqual(git.review_passes_for_pr("7", SHA).status, 1)

    def test_artifact_missing_fetch_failure_and_malformed(self) -> None:
        """Absent artifact, a failed fetch and a malformed line each refuse with their own code."""
        self.assertEqual(self.codes(found(None, status=1)), ["review_artifact_missing"])
        self.assertEqual(self.codes(found(None, status=2, reason="comments")), ["review_artifact_missing"])
        self.assertEqual(self.codes(found(None, status=0)), ["review_passes_malformed"])

    def test_policy_deleted_fails_closed(self) -> None:
        """Negative control: an unreadable policy refuses review_policy_unreadable, never allows."""
        with mock.patch.object(review_passes, "load_policy", side_effect=ValueError("review_policy_unreadable")):
            self.assertEqual(self.codes(found([entry("review-pr")]), DOCS), ["review_policy_unreadable"])

    def test_off_switch_skips_only_the_review_check(self) -> None:
        """review_passes: off skips the check; absent, enforce and unknown values enforce (default ON)."""
        for values, expected in (
            ({}, ["required_review_missing:security-review"]),
            ({"review_passes": "enforce"}, ["required_review_missing:security-review"]),
            ({"review_passes": "bogus"}, ["required_review_missing:security-review"]),
            ({"review_passes": "off"}, []),
        ):
            with (
                self.subTest(values=values),
                mock.patch.object(publication_gate, "load_config", return_value=(values, [])),
            ):
                self.assertEqual(self.codes(found([entry("review-pr")])), expected)

    def test_check_is_registered(self) -> None:
        """The check runs through the one gate, so every publication path gets it."""
        self.assertIn(publication_gate.review_passes_check, publication_gate.CHECKS)


class PathTests(unittest.TestCase):
    """The check is reached from merge.py and from the Claude direct-merge path."""

    def test_merge_py_refuses_missing_security_review(self) -> None:
        """merge.py publishes through publication_gate.enforce; a hooks/ PR without the pass is refused."""
        reply = found([entry("review-pr")])
        with (
            mock.patch.object(git, "review_passes_for_pr", return_value=reply),
            mock.patch.object(manifest_policy, "diff_changes", return_value=HOOKS),
            mock.patch.object(manifest_policy, "violations", return_value=[]),
            self.assertRaises(git.WorkflowError) as caught,
        ):
            publication_gate.enforce("7", SHA)
        self.assertTrue(str(caught.exception).startswith("required_review_missing:security-review"))
        self.assertIn(publication_gate.review_passes_check, publication_gate.CHECKS)
        self.assertTrue(hasattr(merge, "publication_gate"))

    def test_claude_direct_path_returns_the_code(self) -> None:
        """merge_reason denies with the review code first when the gate reports it."""
        violation = [{"code": "required_review_missing:security-review", "detail": "x"}]
        with (
            mock.patch.object(pr_merge_gate, "pr_field", return_value=SHA),
            mock.patch.object(pr_merge_gate, "gate_eval_summary_for_pr", return_value=git.EvalSummary(0, "0", "{}")),
            mock.patch.object(pr_merge_gate, "smoke_verify", return_value=0),
            mock.patch.object(publication_gate, "evaluate", return_value=violation),
        ):
            reason = pr_merge_gate.merge_reason("7", str(REPO))
        self.assertTrue(reason.startswith("required_review_missing:security-review"))
        self.assertNotIn("diff_manifest: off", reason)


if __name__ == "__main__":
    unittest.main()
