"""Root and Codex receipt modules and command matchers stay in sync."""

from __future__ import annotations

import filecmp
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
HOOKS = CODEX / "hooks/scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HOOKS))
from lib import action_match as codex_match  # noqa: E402  # isort: skip
from hooks.scripts.lib import pr_workflow_match as claude_match  # noqa: E402  # isort: skip

MERGE_SHA = "f" * 40

MIRRORS = (
    "scripts/lib/action_receipt.py", "scripts/lib/receipt_signing.py", "scripts/lib/action_binding.py",
    "scripts/authority_keys.py", "scripts/lib/authority_permits.py",
    "scripts/lib/receipt_gate.py", "scripts/lib/merge_budget.py",
)  # fmt: skip


class MirrorTests(unittest.TestCase):
    """The Codex copies of the receipt modules are the Claude files, byte for byte."""

    def test_codex_env_split_string_push_is_guarded(self) -> None:
        """The Codex matcher recognizes a protected ref inside a supported env -S wrapper."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-C", tmp, "symbolic-ref", "HEAD", "refs/heads/feature"], check=True)
            found = codex_match.guarded_operations('env -S "git push origin HEAD:main"', tmp, implicit_push=True)
            self.assertEqual([call.name for call in found], ["git_push"])

    def test_codex_external_time_value_options_do_not_hide_push(self) -> None:
        """GNU time option values precede the executable in the Codex matcher."""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q", tmp], check=True)
            subprocess.run(["git", "-C", tmp, "symbolic-ref", "HEAD", "refs/heads/feature"], check=True)
            command = "/usr/bin/time -f %E -o report git push origin HEAD:main"
            self.assertEqual([call.name for call in codex_match.guarded_operations(command, tmp)], ["git_push"])

    def test_mirrors_byte_identical(self) -> None:
        """Every mirrored file matches its Claude source."""
        for name in MIRRORS:
            with self.subTest(name):
                self.assertTrue(filecmp.cmp(ROOT / name, CODEX / name, shallow=False), name)
        self.assertTrue(
            filecmp.cmp(
                ROOT / "hooks/scripts/lib/headless_command.py",
                CODEX / "hooks/scripts/lib/headless_command.py",
                shallow=False,
            )
        )

    def test_git_directory_selectors_bind_the_same_worktree_on_both_providers(self) -> None:
        """A selected Git directory must resolve to the same physical worktree and Git dir."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            other = Path(tmp) / "other"
            for path in (repo, other):
                subprocess.run(["git", "init", "-q", str(path)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=t@example.com",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "init",
                ],
                check=True,
            )
            linked = Path(tmp) / "linked"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(linked)], check=True)
            self.assertTrue((linked / ".git").is_file())
            alias = Path(tmp) / "alias"
            alias.symlink_to(repo)
            for matcher in (claude_match, codex_match):
                for cwd, target, expected in (
                    (repo, alias, True),
                    (linked, linked, True),
                    (repo, other, False),
                    (linked, repo, False),
                ):
                    call = matcher.operations(f'git -C "{target}" push origin main', str(cwd))[0]
                    self.assertEqual(matcher.same_repository(call, str(cwd)), expected)

    def test_receipt_cli_diff_is_provider_import(self) -> None:
        """Receipt commands differ only in the provider-local command classifier import."""
        claude = (ROOT / "scripts/action_receipt_cli.py").read_text()
        codex = (CODEX / "scripts/action_receipt_cli.py").read_text()
        self.assertEqual(
            claude.replace(
                "from hooks.scripts.lib.pr_workflow_match import Operation, operations",
                "from hooks.scripts.lib.action_match import Operation, operations",
            ).replace(
                "from hooks.scripts.lib.action_match import Operation, operations\nfrom hooks.scripts.lib.trace_row",
                "from hooks.scripts.lib.action_match import Operation, operations\n\nfrom hooks.scripts.lib.trace_row",
            ),
            codex,
        )

    def test_hook_common_has_no_vendored_receipt_code(self) -> None:
        """The vendored receipt_* functions are gone and the file is under its 400-line ceiling."""
        text = (HOOKS / "hook_common.py").read_text()
        for vendored in ("def receipt_", "RECEIPT_FIELDS", "_receipt_claim"):
            self.assertNotIn(vendored, text)
        self.assertLess(len(text.splitlines()), 400)


class MatchParityTests(unittest.TestCase):
    """The vendored command matcher must guard exactly what the Claude one guards."""

    CORPUS = (
        "git push origin main", "git push", "git -C . push origin main",
        "git push origin feature && git push origin main",
        "cd sub && git push", "gh pr merge 5", "gh -R o/r pr merge 5", "gh pr merge 1 && gh pr merge 2",
        "git push --dry-run origin main", "ls", "git push origin HEAD:main", "git merge main", "bash merge.py 7",
        "GIT_DIR=x git push origin main", "git -c a=b push origin main", "git --no-pager push origin main",
        "git commit -m x && git push origin main", "git config a b; gh pr merge 5",
        'git push origin "main"', "git push origin 'HEAD:main'", "git push origin HEAD:$B", "git push --mirror origin",
        "/usr/bin/git push origin HEAD:main", 'eval "git push origin HEAD:main"', "/usr/bin/env git push origin main",
        "git push . evil:feature && git push origin feature:main", "echo x > .git/refs/heads/f; git push origin main",
        "git status 2>&1 && git push origin main", 'cd "sub" && git push origin main', "cd $X && git push origin main",
        "(cd sub); git push origin main", "(cd sub && git push origin main)",
        "cd sub && bash -c 'git push origin main'",
        "gh api --method PUT repos/acme/widgets/pulls/7/merge-async -f sha=ffffffffffffffffffffffffffffffffffffffff",
        "gh api repos/acme/widgets/pulls/7/merge-async/11111111-1111-1111-1111-111111111111",
    )  # fmt: skip

    def test_guarded_segments_identical_on_main_and_feature(self) -> None:
        """Same corpus, same repo state, same (operation, segment, cwd) answers."""
        for branch in ("main", "feature/x"):
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "init", "-q", "-b", branch, tmp], check=True)
                (Path(tmp) / "sub").mkdir()
                for command in self.CORPUS:
                    with self.subTest(branch=branch, command=command):
                        for fn in ("guarded_segments", "state_mutated_before_guard"):
                            args = (command, tmp)[: 2 if fn == "guarded_segments" else 1]
                            self.assertEqual(getattr(claude_match, fn)(*args), getattr(codex_match, fn)(*args))

    def test_unknown_cwd_stays_unbindable_inside_nested_shell(self) -> None:
        """A shell wrapper cannot restore the old cwd after an unknown cd."""
        with tempfile.TemporaryDirectory() as tmp:
            for matcher in (claude_match, codex_match):
                for command in (
                    'cd $UNKNOWN_DIR && bash -c "gh pr merge 516"',
                    "cd $UNKNOWN_DIR && bash -c 'git push origin HEAD:main'",
                ):
                    with self.subTest(matcher=matcher.__name__, command=command):
                        found = matcher.guarded_segments(command, tmp)
                        self.assertEqual(len(found), 1)
                        self.assertTrue(found[0][1].startswith(matcher.UNBINDABLE), found)

    def test_headless_prompts_and_quoted_git_directory_are_guarded_by_both_providers(self) -> None:
        """A child prompt or spaced Git directory cannot hide a protected action."""
        with tempfile.TemporaryDirectory() as tmp:
            for matcher in (claude_match, codex_match):
                for command, expected in (
                    ("codex exec 'gh pr merge 2 --squash'", "merge"),
                    ("claude -p 'gh pr merge 2 --squash'", "merge"),
                    ('git -C "/tmp/path with spaces" push origin HEAD:main', "git_push"),
                ):
                    with self.subTest(matcher=matcher.__name__, command=command):
                        self.assertEqual([name for name, _, _ in matcher.guarded_segments(command, tmp)], [expected])
