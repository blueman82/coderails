#!/usr/bin/env python3
"""Pin action_binding: push binds the refspec source and destination ref; merge binds the live PR; else None."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_test_support import ORIGIN, REPOSITORY, git, make_repo
from scripts.lib import action_binding as ab


class RepositoryTests(unittest.TestCase):
    """Remote URLs normalise to lower-case host/owner/name or to None."""

    def test_normalise(self) -> None:
        """https, scp-style and ssh forms agree; paths and bare names are unknowable."""
        for url in (
            ORIGIN,
            "git@github.com:Acme/Widgets.git",
            "ssh://git@github.com/acme/widgets",
            "https://github.com/acme/widgets/",
        ):
            self.assertEqual(ab.normalise_repository(url), REPOSITORY, url)
        for url in ("/tmp/x/y.git", "origin", "", "file:///tmp/x/y.git"):
            self.assertIsNone(ab.normalise_repository(url), url)

    def test_ports_and_path_segments_are_canonical(self) -> None:
        """An SSH port is not a path component, and traversal cannot name a repository."""
        self.assertEqual(ab.normalise_repository("ssh://git@github.com:2222/acme/widgets.git"), REPOSITORY)
        for url in (
            "https://github.com/acme/../widgets.git",
            "https://github.com/acme/x/../widgets.git",
            "git@github.com:22/acme/widgets.git",
        ):
            self.assertIsNone(ab.normalise_repository(url), url)


class PushTests(unittest.TestCase):
    """git push binds (remote repository, destination full ref, rev-parse of the refspec source)."""

    def setUp(self) -> None:
        """Repo on main with a diverging feature branch checked out."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = make_repo(Path(tmp.name) / "r")
        self.main = git(self.repo, "rev-parse", "main")
        git(self.repo, "switch", "-q", "-c", "feature")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "two")
        git(self.repo, "switch", "-q", "main")
        git(self.repo, "switch", "-q", "-c", "other")
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "three")
        self.feature = git(self.repo, "rev-parse", "feature")
        self.head = git(self.repo, "rev-parse", "HEAD")

    def bind(self, command: str) -> dict[str, str] | None:
        """Binding for a push command run in the repo."""
        return ab.binding("git_push", command, str(self.repo))

    def test_refspec_source_not_head(self) -> None:
        """`git push origin feature:main` pushes feature to refs/heads/main even though HEAD is elsewhere."""
        want = {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": self.feature}
        self.assertEqual(self.bind("git push origin feature:main"), want)
        self.assertNotEqual(self.feature, self.head)

    def test_other_forms(self) -> None:
        """Bare name, HEAD:dst, +force prefix, full ref, -C, implicit and remote-only pushes."""
        self.assertEqual(
            self.bind("git push origin main"), {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": self.main}
        )
        self.assertEqual(self.bind("git push origin HEAD:main")["sha"], self.head)  # type: ignore[index]
        self.assertEqual(self.bind("git push origin +feature:release/x")["ref"], "refs/heads/release/x")  # type: ignore[index]
        self.assertEqual(self.bind("git push origin feature:refs/heads/main")["ref"], "refs/heads/main")  # type: ignore[index]
        self.assertEqual(self.bind("git push -o ci.skip origin main")["sha"], self.main)  # type: ignore[index]
        self.assertEqual(ab.binding("git_push", "git -C r push origin main", str(self.repo.parent))["sha"], self.main)  # type: ignore[index]
        selected = f"git --no-pager -C '{self.repo}' push origin main"
        self.assertEqual(self.bind(selected), self.bind("git push origin main"))
        self.assertEqual(self.bind(f"git -C '{self.repo}' --no-pager push origin main"), self.bind(selected))

    def test_head_without_dest_binds_the_current_branch(self) -> None:
        """`git push origin HEAD` pushes to the current branch's ref, never refs/heads/HEAD; detached is unknowable."""
        want = {"repository": REPOSITORY, "ref": "refs/heads/other", "sha": self.head}
        self.assertEqual(self.bind("git push origin HEAD"), want)
        git(self.repo, "checkout", "-q", "--detach")
        self.assertIsNone(self.bind("git push origin HEAD"))

    def test_unknowable_is_none(self) -> None:
        """Deletes, several refspecs, --all/--mirror/--tags, bare pushes, unknown remote/source and junk give None."""
        for command in (
            "git push origin :main", "git push --delete origin main", "git push --all origin", "git push --mirror",
            "git push origin --tags", "git push origin a b", "git push upstream main", "git push origin nosuch:main",
            "git push 'origin", "git push origin main extra extra", "git push", "git push origin",
        ):  # fmt: skip
            self.assertIsNone(self.bind(command), command)

    def test_retargeting_forms_are_none(self) -> None:
        """Env prefixes, -c, --git-dir and --work-tree could point the push elsewhere: unknowable, so denied."""
        for command in (
            "GIT_DIR=/x git push origin main", "GIT_CONFIG_COUNT=1 git push origin main",
            "git -c remote.origin.pushurl=https://evil/x.git push origin main", "git --git-dir=/x push origin main",
            "git --work-tree /x push origin main", "env GIT_DIR=/x git push origin main",
        ):  # fmt: skip
            self.assertIsNone(self.bind(command), command)

    def test_destination_and_transport_overrides_are_unbindable(self) -> None:
        """A transport or destination override may change the actual push target."""
        for command in (
            "git push --repo evil origin main",
            "git push --repo=evil origin main",
            "git push --receive-pack=evil origin main",
            "git push --exec=evil origin main",
            "git push --mirror=true origin main",
            "git push --delete=true origin main",
        ):
            with self.subTest(command=command):
                self.assertIsNone(self.bind(command))

    def test_push_url_redirect_is_seen(self) -> None:
        """remote.<n>.pushurl is where the push really goes, so the repository follows it (negative control)."""
        git(self.repo, "config", "remote.origin.pushurl", "git@github.com:evil/widgets.git")
        self.assertEqual(self.bind("git push origin main")["repository"], "github.com/evil/widgets")  # type: ignore[index]

    def test_wrong_remote_changes_repository(self) -> None:
        """A second remote with another owner binds that repository, not origin's."""
        git(self.repo, "remote", "add", "fork", "git@github.com:evil/widgets.git")
        self.assertEqual(self.bind("git push fork main")["repository"], "github.com/evil/widgets")  # type: ignore[index]


class MergeTests(unittest.TestCase):
    """gh pr merge binds the PR base and the live head sha; any failure is None."""

    def setUp(self) -> None:
        """Repo with origin."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = make_repo(Path(tmp.name) / "r")

    def test_live_pr(self) -> None:
        """Base and head come from pr_view; origin supplies the repository."""
        a = "a" * 40
        with mock.patch.object(ab, "pr_view", return_value=("main", a)) as view:
            got = ab.binding("merge", f"gh pr merge 12 --squash --match-head-commit {a}", str(self.repo))
        self.assertEqual(got, {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": a})
        view.assert_called_once_with("12", str(self.repo), None)

    def test_merge_script_resolves_auto_and_branch_target(self) -> None:
        """Supported merge.py targets bind the same PR that the helper resolves."""
        sha = "a" * 40
        git(self.repo, "switch", "-q", "-c", "feature/x")
        with (
            mock.patch.object(ab, "pr_view", return_value=("main", sha)),
            mock.patch.object(ab, "pr_number_for_branch", return_value="7") as number,
        ):
            for target in ("auto", "feature/x"):
                with self.subTest(target=target):
                    self.assertEqual(
                        ab.binding("merge", f"python3 scripts/merge.py {target} --expected-head {sha}", str(self.repo)),
                        {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": sha},
                    )
        self.assertEqual([call.args[0] for call in number.call_args_list], ["feature/x", "feature/x"])

    def test_nonzero_gh_json_cannot_supply_a_binding(self) -> None:
        """A failed gh process can print JSON, but it did not establish a live PR head."""
        done = subprocess.CompletedProcess([], 1, '{"baseRefName":"main","headRefOid":"' + "a" * 40 + '"}', "failed")
        with mock.patch("scripts.lib.action_binding.subprocess.run", return_value=done):
            self.assertIsNone(ab.pr_view("12", str(self.repo)))

    def test_head_must_be_pinned(self) -> None:
        """No --match-head-commit, or a stale one, is unknowable (a head that moves later merges unreviewed code)."""
        a = "a" * 40
        with mock.patch.object(ab, "pr_view", return_value=("main", a)):
            for command in ("gh pr merge 12", f"gh pr merge 12 --match-head-commit {'b' * 40}"):
                self.assertIsNone(ab.binding("merge", command, str(self.repo)), command)
            self.assertIsNotNone(ab.binding("merge", f"gh pr merge --match-head-commit={a} 12", str(self.repo)))
            self.assertIsNone(ab.binding("merge", "gh api repos/acme/widgets/pulls/9/merge -X PUT", str(self.repo)))
            self.assertIsNotNone(
                ab.binding("merge", f"gh api repos/acme/widgets/pulls/9/merge -f sha={a}", str(self.repo))
            )
            self.assertIsNone(ab.binding("merge", "python3 scripts/merge.py 12", str(self.repo)))

    def test_merge_script_requires_the_current_expected_head(self) -> None:
        """Only a literal head that matches the live PR can bind a helper receipt."""
        approved = "a" * 40
        later = "b" * 40
        with mock.patch.object(ab, "pr_view", return_value=("main", approved)) as view:
            self.assertIsNone(ab.binding("merge", "python3 scripts/merge.py 12", str(self.repo)))
            view.assert_not_called()
            view.return_value = ("main", later)
            self.assertIsNone(
                ab.binding("merge", f"python3 scripts/merge.py 12 --expected-head {approved}", str(self.repo))
            )
            self.assertEqual(
                ab.binding("merge", f"python3 scripts/merge.py 12 --expected-head {later}", str(self.repo)),
                {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": later},
            )
            self.assertEqual(
                ab.binding("merge", f"gh pr merge 12 --match-head-commit {later}", str(self.repo)),
                {"repository": REPOSITORY, "ref": "refs/heads/main", "sha": later},
            )

    def test_forms(self) -> None:
        """PR URL, gh api path and -R pick the repository; option values are never mistaken for the PR."""
        b = "b" * 40
        pin = f"--match-head-commit {b}"
        with mock.patch.object(ab, "pr_view", return_value=("release/x", b)) as view:
            by_url = ab.binding("merge", f"gh pr merge https://github.com/other/repo/pull/7 {pin}", str(self.repo))
            self.assertEqual(by_url and by_url["ref"], "refs/heads/release/x")
            self.assertEqual(by_url and by_url["repository"], "github.com/other/repo")
            api = ab.binding("merge", f"gh api repos/acme/gadgets/pulls/9/merge -f sha={b}", str(self.repo))
            self.assertEqual(api and api["repository"], "github.com/acme/gadgets")
            async_api = ab.binding(
                "merge", f"gh api --method PUT repos/acme/gadgets/pulls/9/merge-async -f sha={b}", str(self.repo)
            )
            self.assertIsNone(async_api)  # async merge may also merge open downstack PRs
            self.assertIsNone(
                ab.binding("merge", "gh api repos/acme/gadgets/pulls/9/merge-async/some-uuid", str(self.repo))
            )
            got = ab.binding("merge", f"gh pr merge 3 -R other/repo {pin}", str(self.repo))
            body = ab.binding("merge", f"gh pr merge --body 7 5 {pin}", str(self.repo))
        self.assertEqual(got and got["repository"], "github.com/other/repo")
        self.assertIsNotNone(body)
        self.assertEqual([c.args[:3] for c in view.call_args_list][0], ("7", str(self.repo), "github.com/other/repo"))
        self.assertEqual([c.args[0] for c in view.call_args_list], ["7", "9", "3", "5"])

    def test_unknowable_is_none(self) -> None:
        """No PR number, a branch name, two PRs, a URL/-R clash, a failed gh call, an env prefix or no origin: None."""
        c = "c" * 40
        pin = f"--match-head-commit {c}"
        with mock.patch.object(ab, "pr_view", return_value=None):
            self.assertIsNone(ab.binding("merge", f"gh pr merge 12 {pin}", str(self.repo)))
        with mock.patch.object(ab, "pr_view", return_value=("main", c)):
            for command in (
                f"gh pr merge --squash {pin}", f"gh pr merge my-branch {pin}", f"gh pr merge 1 2 {pin}",
                f"gh pr merge https://github.com/o/r/pull/5 -R x/y {pin}", f"GH_REPO=evil/x gh pr merge 5 {pin}",
                f"gh pr merge -bR 5 {pin}", "python3 scripts/merge.py",
            ):  # fmt: skip
                self.assertIsNone(ab.binding("merge", command, str(self.repo)), command)
            git(self.repo, "remote", "remove", "origin")
            self.assertIsNone(ab.binding("merge", f"gh pr merge 12 {pin}", str(self.repo)))
        self.assertIsNone(ab.binding("other", "x", str(self.repo)))


if __name__ == "__main__":
    unittest.main()
