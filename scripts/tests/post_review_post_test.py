"""post_review.py post: argument gate before any gh call, derived passes, dedupe, stale-head refusal, docs shape."""

from __future__ import annotations

import io
import json
import re
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable, cast
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts/integrity-gate"))
from scripts import post_review  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import review_artifact, review_passes  # noqa: E402

review_valid = cast(
    Callable[[str, int, str], bool],
    runpy.run_path(str(REPO / "scripts/integrity-gate/integrity_evidence.py"))["review_valid"],
)
SHA, OTHER = "a" * 40, "b" * 40
CLEAN = "## No findings\n"
CRITICAL = "## Critical\n- injection\n\n## Important\nNone\n\n## Suggestions\nNone\n"
URL = "https://github.com/o/r/pull/12#issuecomment-1"


class FakeGh:
    """Stand-in for git.run: scripted PR heads, an existing-comment list, and a record of posted bodies."""

    def __init__(self, heads: list[str], existing: list[dict[str, str]] | None = None) -> None:
        """Script the PR head replies and the comments already on the PR."""
        self.heads: list[str] = list(heads)
        self.existing: list[dict[str, str]] = existing or []
        self.calls: list[tuple[str, ...]] = []
        self.posted: list[str] = []

    def __call__(self, *argv: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        """Answer one argv list."""
        self.calls.append(argv)
        out = ""
        if argv[:3] == ("gh", "pr", "view"):
            out = self.heads.pop(0) if len(self.heads) > 1 else self.heads[0]
        elif argv[:3] == ("git", "remote", "get-url"):
            out = "https://github.com/o/r.git"
        elif argv[:3] == ("gh", "api", "user"):
            out = "me"
        elif argv[0] == "gh" and argv[1] == "api" and "-F" in argv:
            self.posted.append(Path(argv[argv.index("-F") + 1].removeprefix("body=@")).read_text())
            out = json.dumps({"url": URL, "author": "me", "created": "2026-10-05T00:00:00Z"})
        elif argv[0] == "gh" and argv[1] == "api":
            out = "\n".join(json.dumps(c) for c in self.existing)
        return subprocess.CompletedProcess(argv, 0, out + "\n", "")


class PostTests(unittest.TestCase):
    """The post operation end to end over a scripted gh."""

    def setUp(self) -> None:
        """Summary files in a temp dir."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.clean, self.critical = self.dir / "clean.md", self.dir / "critical.md"
        self.clean.write_text(CLEAN)
        self.critical.write_text(CRITICAL)

    def run_post(self, fake: FakeGh, *arguments: str) -> tuple[int, str, str]:
        """Run main over the fake gh; returns (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(git, "run", side_effect=fake),
            mock.patch.object(post_review, "cache_path", return_value=None, create=True),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = post_review.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_posts_marker_then_passes_line_derived_from_files(self) -> None:
        """First line is the unchanged v1 marker, second the passes line; verdicts come from the file text."""
        fake = FakeGh([SHA])
        code, out, _ = self.run_post(
            fake, "post", "12", "--summary", str(self.clean), "--pass", f"security-review={self.critical}"
        )
        self.assertEqual(code, 0)
        self.assertIn(URL, out)
        lines = fake.posted[0].splitlines()
        self.assertEqual(lines[0], review_artifact.marker("12", SHA))
        passes = review_passes.parse(fake.posted[0], "12", SHA)
        self.assertEqual(lines[1], review_passes.render(SHA, passes or []))
        self.assertEqual(
            [(p["name"], p["verdict"], p["blocking"]) for p in passes or []],
            [("review-pr", "pass", False), ("security-review", "fail", True)],
        )
        self.assertEqual(passes[1]["summary_sha256"], review_passes.summary_sha256(CRITICAL))  # type: ignore[index]
        self.assertIn(CRITICAL, fake.posted[0])

    def test_posts_server_compatible_companion_after_passes(self) -> None:
        """The final comment has only the v1 marker and the same general summary."""
        fake = FakeGh([SHA])
        code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.posted), 2)
        self.assertEqual(fake.posted[1], review_artifact.marker("12", SHA) + "\n" + CLEAN)
        self.assertFalse(review_valid(fake.posted[0], 12, SHA))
        self.assertTrue(review_valid(fake.posted[1], 12, SHA))

    def test_compat_pair_is_consumed_and_mismatch_refused(self) -> None:
        """A preserve-compat line binds both comments; changing either comment breaks the pair."""
        summary = "## Critical\nNone\n\n## Important\n- Retained compatibility\n\n## Suggestions\nNone\n"
        finding = self.dir / "finding.md"
        finding.write_text(summary)
        fake = FakeGh([SHA])
        code, _, err = self.run_post(
            fake, "post", "12", "--summary", str(finding), "--compat-count", "1", "--disposition", "preserve-compat"
        )
        self.assertEqual(code, 0, err)
        compat = review_artifact.compat_line("12", SHA, 1, "preserve-compat")
        self.assertEqual(fake.posted[1], review_artifact.marker("12", SHA) + "\n" + compat + "\n" + summary)
        self.assertTrue(review_valid(fake.posted[1], 12, SHA))
        with mock.patch.object(git, "trusted_comment_bodies", return_value=fake.posted):
            found = git.review_passes_for_pr("12", SHA)
        self.assertEqual(found.status, 0)
        self.assertEqual([p["name"] for p in found.passes or ()], ["review-pr"])
        for changed in (
            [fake.posted[0], fake.posted[1].replace("count=1", "count=2")],
            [fake.posted[0].replace("count=1", "count=bad"), fake.posted[1]],
            [fake.posted[0].replace("count=1", "count=2"), fake.posted[1]],
            [fake.posted[0], fake.posted[1].replace("head_sha=" + SHA, "head_sha=" + OTHER)],
        ):
            with self.subTest(changed=changed), mock.patch.object(git, "trusted_comment_bodies", return_value=changed):
                self.assertIsNone(git.review_passes_for_pr("12", SHA).passes)

    def test_partial_post_adds_only_the_companion(self) -> None:
        """A failed second post can resume without publishing a second pass record."""
        first = FakeGh([SHA])
        self.run_post(first, "post", "12", "--summary", str(self.clean))
        existing = [{"url": URL, "author": "me", "created": "t", "body": first.posted[0]}]
        fake = FakeGh([SHA], existing)
        code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.posted, [first.posted[1]])

    def test_eval_after_review_does_not_repost_pair(self) -> None:
        """The usual GO eval comment may follow the review pair."""
        first = FakeGh([SHA])
        self.run_post(first, "post", "12", "--summary", str(self.clean))
        existing = [{"url": URL, "author": "me", "created": "t", "body": body} for body in first.posted]
        existing.append(
            {"url": URL + "-eval", "author": "me", "created": "t", "body": "<!-- coderails-eval-summary -->"}
        )
        fake = FakeGh([SHA], existing)
        code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.posted, [])

    def test_head_change_between_posts_stops_before_companion(self) -> None:
        """The server companion is never written after the PR head changes."""
        fake = FakeGh([SHA, SHA, OTHER])
        code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertNotEqual(code, 0)
        self.assertEqual(len(fake.posted), 1)
        self.assertIn("stale", err)

    def test_posted_body_still_parses_for_dashboard_and_integrity_gate(self) -> None:
        """Compat: the dashboard prGates regex and the integrity gate's line test match the unchanged first line."""
        fake = FakeGh([SHA])
        self.run_post(fake, "post", "12", "--summary", str(self.clean))
        body = fake.posted[0]
        dashboard = re.compile(r"^<!-- coderails-review-summary v1 pr=(\S+) head_sha=(\S+) -->$")
        hits = [m for line in body.split("\n") if (m := dashboard.match(line))]
        self.assertEqual([(m[1], m[2]) for m in hits], [("12", SHA)])
        self.assertIn(f"<!-- coderails-review-summary v1 pr=12 head_sha={SHA} -->", body.splitlines())

    def test_identical_existing_artifact_is_reused(self) -> None:
        """Negative control for posting: an identical first-two-lines comment by me means no second post."""
        first = FakeGh([SHA])
        self.run_post(first, "post", "12", "--summary", str(self.clean))
        existing = [{"url": URL, "author": "me", "created": "t", "body": body} for body in first.posted]
        fake = FakeGh([SHA], existing)
        code, out, _ = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual((code, fake.posted), (0, []))
        self.assertIn("already posted", out)
        self.assertIn(URL, out)

    def test_other_authors_identical_comment_is_not_reused(self) -> None:
        """A comment by someone else is not the trusted artifact, so the post still happens."""
        first = FakeGh([SHA])
        self.run_post(first, "post", "12", "--summary", str(self.clean))
        existing = [{"url": URL, "author": "mallory", "created": "t", "body": first.posted[0]}]
        fake = FakeGh([SHA], existing)
        self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual(len(fake.posted), 2)

    def test_dedupe_uses_the_newest_valid_same_head_artifact(self) -> None:
        """An older matching marker or a corrupt matching tail must not suppress a repairing post."""
        first = FakeGh([SHA])
        self.run_post(first, "post", "12", "--summary", str(self.clean))
        good = {"url": URL, "author": "me", "created": "t", "body": first.posted[0]}
        companion = {**good, "body": first.posted[1]}
        failed = FakeGh([SHA])
        self.run_post(failed, "post", "12", "--summary", str(self.critical))
        corrupt = "\n".join(first.posted[0].splitlines()[:2]) + "\n" + CRITICAL
        for existing in ([{**good, "body": corrupt}], [good, {**good, "body": failed.posted[0]}]):
            with self.subTest(existing=existing):
                fake = FakeGh([SHA], existing)
                code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
                self.assertEqual(code, 0, err)
                self.assertEqual(len(fake.posted), 2)
        fake = FakeGh([SHA], [good, {**companion, "url": URL + "-new"}])
        code, out, _ = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual((code, fake.posted), (0, []))
        self.assertIn(URL + "-new", out)
        fake = FakeGh([SHA], [good, companion, {**good, "author": "mallory", "body": corrupt}])
        code, out, _ = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertEqual((code, fake.posted), (0, []))
        self.assertIn(URL, out)

    def test_duplicate_summary_headings_never_reach_gh(self) -> None:
        """Conflicting repeats cannot derive a pass from their first severity section."""
        bad = self.dir / "duplicate.md"
        bad.write_text(CRITICAL.replace("- injection", "None") + "\n" + CRITICAL)
        fake = FakeGh([SHA])
        code, _, _ = self.run_post(fake, "post", "12", "--summary", str(bad))
        self.assertNotEqual(code, 0)
        self.assertEqual(fake.calls, [])

    def test_head_change_before_post_is_refused(self) -> None:
        """A head that moves between the first read and the pre-post re-fetch posts nothing."""
        fake = FakeGh([SHA, OTHER])
        code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertNotEqual(code, 0)
        self.assertEqual(fake.posted, [])
        self.assertIn("stale", err)

    def test_head_change_after_post_is_reported_stale(self) -> None:
        """A head that moves after the post is a failure: the artifact is for the old head, so it must not be used."""
        fake = FakeGh([SHA, SHA, OTHER])
        code, _, err = self.run_post(fake, "post", "12", "--summary", str(self.clean))
        self.assertNotEqual(code, 0)
        self.assertIn("stale", err)

    def test_bad_pr_number_makes_no_gh_call(self) -> None:
        """Negative control: injection-shaped or non-positive numbers exit non-zero, pr_number_invalid, zero runs."""
        for bad in ("7; id", "$(id)", "-1", "0", "07", "abc", ""):
            with self.subTest(bad=bad):
                fake = FakeGh([SHA])
                code, _, err = self.run_post(fake, "post", bad, "--summary", str(self.clean))
                self.assertNotEqual(code, 0)
                self.assertIn("pr_number_invalid", err)
                self.assertEqual(fake.calls, [])

    def test_invalid_summary_makes_no_gh_call(self) -> None:
        """validate_summary runs on every file before any network step."""
        bad = self.dir / "bad.md"
        bad.write_text("## Critical\n- x\n")
        for arguments in (("--summary", str(bad)), ("--summary", str(self.clean), "--pass", f"security-review={bad}")):
            fake = FakeGh([SHA])
            code, _, _ = self.run_post(fake, "post", "12", *arguments)
            self.assertNotEqual(code, 0)
            self.assertEqual(fake.calls, [])

    def test_server_rejected_heading_forms_never_post(self) -> None:
        """The local validator rejects summary forms the existing server parser rejects."""
        variants = (
            "## Important\nNone\n## Critical\nNone\n## Suggestions\nNone\n",
            "## Critical\nNone\n## Extra\nNone\n## Important\nNone\n## Suggestions\nNone\n",
            "## No findings\n## Extra\nNone\n",
            "## No findings\nexplanation\n",
        )
        for text in variants:
            with self.subTest(text=text):
                self.assertFalse(review_valid(review_artifact.marker("12", SHA) + "\n" + text, 12, SHA))
                invalid = self.dir / "invalid.md"
                invalid.write_text(text)
                fake = FakeGh([SHA])
                code, _, _ = self.run_post(fake, "post", "12", "--summary", str(invalid))
                self.assertNotEqual(code, 0)
                self.assertEqual(fake.calls, [])

    def test_none_mixed_with_findings_is_rejected(self) -> None:
        """A Critical section that says None and also lists a finding is ambiguous and not postable."""
        mixed = self.dir / "mixed.md"
        mixed.write_text("## Critical\nNone\n* SQL injection\n\n## Important\nNone\n\n## Suggestions\nNone\n")
        with self.assertRaises(ValueError):
            post_review.validate_summary(mixed)
        post_review.validate_summary(self.critical)  # negative control: a plain bullet is still valid

    def test_pass_name_must_be_plain_and_unique(self) -> None:
        """Pass names are lowercase words; review-pr and duplicates are rejected."""
        for pass_arg in (f"Bad Name={self.clean}", f"review-pr={self.clean}", f"a={self.clean}"):
            fake = FakeGh([SHA])
            arguments = ["--pass", pass_arg] + (["--pass", pass_arg] if pass_arg.startswith("a=") else [])
            code, _, _ = self.run_post(fake, "post", "12", "--summary", str(self.clean), *arguments)
            self.assertNotEqual(code, 0)
            self.assertEqual(fake.posted, [])

    def test_existing_operations_unchanged(self) -> None:
        """The validate operation keeps its old interface."""
        self.assertEqual(post_review.main(["validate", str(self.clean)]), 0)

    def test_claude_copy_writes_the_progress_cache(self) -> None:
        """The Claude copy keeps the progress.json cache write after posting."""
        progress = self.dir / "progress.json"
        progress.write_text("{}")
        fake = FakeGh([SHA])
        with (
            mock.patch.object(git, "run", side_effect=fake),
            mock.patch.object(post_review, "cache_path", return_value=progress),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(post_review.main(["post", "12", "--summary", str(self.clean)]), 0)
        cache: dict[str, Any] = json.loads(progress.read_text())["review"]
        self.assertEqual((cache["pr"], cache["head_sha"], cache["summary_url"]), (12, SHA, URL))


FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


class DocsShapeTests(unittest.TestCase):
    """The command and the Codex skill hold no shell that interpolates the argument or a $$ temp file."""

    def test_no_arguments_or_pid_in_code_blocks(self) -> None:
        """Neither document has $ARGUMENTS or $$ inside a fenced block, and both name the one script command."""
        for path in (REPO / "commands/post-review.md", REPO / "packages/codex/skills/post-review/SKILL.md"):
            text = path.read_text()
            blocks = "\n".join(FENCE.findall(text))
            with self.subTest(path=str(path)):
                self.assertNotIn("$ARGUMENTS", blocks)
                self.assertNotIn("$$", blocks)
                self.assertIn("post_review.py", text)
                self.assertRegex(text, r"post <PR[^>]*> --summary")


if __name__ == "__main__":
    unittest.main()
