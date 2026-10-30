"""Check the sandbox launcher with real Git and a fake worker process."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.receipt_test_support import git
from scripts.sandbox import spawn_sandboxed_worker

PARENT_SECRETS = {"GH_TOKEN": "parent-gh", "GITHUB_TOKEN": "parent-github", "ANTHROPIC_API_KEY": "parent-key"}


class LauncherFlowTests(unittest.TestCase):
    """Real git, a fake worker command: the commit lands in the scratch clone and only that branch is imported."""

    def setUp(self) -> None:
        """A bare origin, a primary repo with two branches and a linked worktree on the worker branch."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.origin = self.root / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        self.primary = self.root / "primary"
        self.primary.mkdir()
        git(self.primary, "init", "-q", "-b", "main")
        git(self.primary, "remote", "add", "origin", str(self.origin))
        git(self.primary, "commit", "-q", "--allow-empty", "-m", "base")
        git(self.primary, "branch", "other")
        git(self.primary, "push", "-q", "origin", "main", "other")
        self.worktree = self.root / "wt"
        git(self.primary, "worktree", "add", "-q", "-b", "feature/x", str(self.worktree))
        self.prompt = self.root / "prompt.txt"
        self.prompt.write_text("do the unit\n")
        self.home = self.root / "home"
        credential = self.home / ".coderails/worker_credential"
        credential.parent.mkdir(parents=True)
        credential.write_text("ANTHROPIC_API_KEY=sk-worker\n")
        credential.chmod(0o600)
        (self.root / "tmp").mkdir()
        self.seen: dict[str, Any] = {}
        env = {
            "HOME": str(self.home),
            "TMPDIR": str(self.root / "tmp"),
            "CODERAILS_HEADLESS_RUN": "1",
            **PARENT_SECRETS,
        }
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        shim = patch.object(shutil, "which", return_value="/fixture/tool")
        shim.start()
        self.addCleanup(shim.stop)
        runtime = patch("scripts.sandbox.containment.runtime_present", return_value=True)
        runtime.start()
        self.addCleanup(runtime.stop)
        manifest = patch.object(spawn_sandboxed_worker, "declared_manifest", return_value=["**"])
        manifest.start()
        self.addCleanup(manifest.stop)

    def refs(self, repo: Path) -> dict[str, str]:
        """refs/heads name -> object id."""
        rows = git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads").splitlines()
        return {name.removeprefix("refs/heads/"): oid for name, oid in (row.split() for row in rows)}

    @staticmethod
    def drop_state(state: Path) -> None:
        """Remove the empty provider state directory render_settings created for a fixture clone."""
        if state.is_dir():
            state.rmdir()

    def run_launcher(self, worker: Callable[[Path], int | None]) -> int:
        """Run launch() with the srt child replaced by `worker(arguments, cwd, env)`; return its exit status."""

        def fake(arguments: list[str], cwd: str, env: dict[str, str], log: IO[bytes]) -> int:
            self.seen = {"arguments": arguments, "cwd": cwd, "env": dict(env)}
            state = Path(f"/private/tmp/claude-{os.getuid()}") / cwd.replace("/", "-")
            self.addCleanup(self.drop_state, state)
            return int(worker(Path(cwd)) or 0)

        with (
            patch.object(spawn_sandboxed_worker, "stream_child", fake),
            patch.object(subprocess, "run", wraps=subprocess.run) as run,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            try:
                return spawn_sandboxed_worker.launch(str(self.worktree), str(self.prompt), "sonnet")
            finally:
                self.calls = [list(call.args[0]) for call in run.call_args_list if call.args]

    def commit(self, clone: Path, branch: str, name: str = "w") -> None:
        """Commit inside the scratch clone on `branch`."""
        git(clone, "checkout", "-q", "-B", branch)
        git(clone, "commit", "-q", "--allow-empty", "-m", name)

    def test_commit_lands_in_clone_then_only_the_worker_branch_is_imported_and_pushed(self) -> None:
        """(c) The primary .git is never the worker's cwd; main/other refs are byte-identical; the launcher pushes."""
        before = self.refs(self.primary)
        self.assertEqual(self.run_launcher(lambda clone: self.commit(clone, "feature/x")), 0)
        clone = Path(self.seen["cwd"])
        self.assertEqual(clone.parent.parent, self.root / "tmp")
        common = git(clone, "rev-parse", "--path-format=absolute", "--git-common-dir")
        self.assertEqual(Path(common), clone / ".git")
        after = self.refs(self.primary)
        self.assertEqual(
            {k: v for k, v in after.items() if k != "feature/x"}, {k: v for k, v in before.items() if k != "feature/x"}
        )
        self.assertEqual(after["feature/x"], git(clone, "rev-parse", "feature/x"))
        self.assertNotEqual(after["feature/x"], before["feature/x"])
        self.assertEqual(git(self.origin, "rev-parse", "feature/x"), after["feature/x"])
        self.assertEqual(git(self.worktree, "status", "--porcelain"), "")
        self.assertEqual(git(self.primary, "rev-parse", "refs/heads/main"), before["main"])
        self.assertFalse(any(call[:1] == ["gh"] for call in self.calls), self.calls)

    def test_primary_branch_move_after_merge_cannot_publish_unchecked_commit(self) -> None:
        """A primary commit added after the checked worker merge must not reach origin."""
        remote_before = git(self.origin, "for-each-ref", "refs/heads/feature/x")
        original_git = spawn_sandboxed_worker.git

        def race(repo: str | Path, *arguments: str, hardened: bool = False) -> str:
            result = original_git(repo, *arguments, hardened=hardened)
            if Path(repo) == self.worktree and arguments[:2] == ("merge", "--ff-only"):
                (self.worktree / "unchecked.txt").write_text("outside worker review\n")
                git(self.worktree, "add", "unchecked.txt")
                git(self.worktree, "commit", "-q", "-m", "unchecked")
            return result

        with (
            patch.object(spawn_sandboxed_worker, "git", side_effect=race),
            self.assertRaisesRegex(ValueError, "branch_import_refused"),
        ):
            self.run_launcher(lambda clone: self.commit(clone, "feature/x"))
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads/feature/x"), remote_before)

    def test_primary_branch_move_before_import_is_refused(self) -> None:
        """Even a primary fast-forward to the worker tip invalidates the clone-time branch check."""
        remote_before = git(self.origin, "for-each-ref", "refs/heads/feature/x")

        def worker(clone: Path) -> None:
            self.commit(clone, "feature/x")
            git(self.worktree, "fetch", "-q", str(clone), "feature/x")
            git(self.worktree, "merge", "--ff-only", "-q", "FETCH_HEAD")

        with self.assertRaisesRegex(ValueError, "branch_import_refused"):
            self.run_launcher(worker)
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads/feature/x"), remote_before)

    def test_push_uses_checked_worker_tip_if_primary_branch_moves_later(self) -> None:
        """A branch move at push time cannot change the commit selected for publication."""
        original_git = spawn_sandboxed_worker.git

        def race(repo: str | Path, *arguments: str, hardened: bool = False) -> str:
            if Path(repo) == self.worktree and arguments[:2] == ("push", "--quiet"):
                (self.worktree / "unchecked.txt").write_text("outside worker review\n")
                git(self.worktree, "add", "unchecked.txt")
                git(self.worktree, "commit", "-q", "-m", "unchecked")
            return original_git(repo, *arguments, hardened=hardened)

        with patch.object(spawn_sandboxed_worker, "git", side_effect=race):
            self.assertEqual(self.run_launcher(lambda clone: self.commit(clone, "feature/x")), 0)
        worker_tip = git(Path(self.seen["cwd"]), "rev-parse", "feature/x")
        self.assertEqual(git(self.origin, "rev-parse", "feature/x"), worker_tip)
        self.assertNotEqual(git(self.worktree, "rev-parse", "HEAD"), worker_tip)

    def test_missing_graph_identity_cannot_publish(self) -> None:
        """A direct launcher invocation without graph identity may run, but cannot import or push a commit."""
        before, pushed = self.refs(self.primary), git(self.origin, "for-each-ref", "refs/heads")

        def worker(clone: Path) -> None:
            (clone / "unscoped.txt").write_text("unscoped")
            git(clone, "add", "unscoped.txt")
            git(clone, "commit", "-q", "-m", "unscoped")

        with (
            patch.object(spawn_sandboxed_worker, "declared_manifest", return_value=None),
            self.assertRaisesRegex(ValueError, "branch_import_refused.*manifest"),
        ):
            self.run_launcher(worker)
        self.assertEqual(self.refs(self.primary), before)
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads"), pushed)

    def test_child_environment_is_an_allowlist(self) -> None:
        """(b) No parent GH_TOKEN/GITHUB_TOKEN/ANTHROPIC_API_KEY, no real HOME, no headless flag."""
        self.run_launcher(lambda clone: None)
        env, scratch = self.seen["env"], Path(self.seen["cwd"]).parent
        allowed = {
            "PATH",
            "LANG",
            "TERM",
            "HOME",
            "TMPDIR",
            "CLAUDE_CONFIG_DIR",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "npm_config_cache",
            "npm_config_offline",
            "ANTHROPIC_API_KEY",
        }
        self.assertLessEqual(set(env), allowed)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-worker")
        self.assertEqual(env.get("npm_config_offline"), "true")
        self.assertNotIn("CODERAILS_HEADLESS_RUN", env)
        self.assertNotEqual(env["HOME"], str(self.home))
        for name in (
            "HOME",
            "TMPDIR",
            "CLAUDE_CONFIG_DIR",
            "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
        ):
            self.assertTrue(Path(env[name]).is_relative_to(scratch), name)
        settings = json.loads((scratch / "srt-settings.json").read_text())
        self.assertEqual(settings["filesystem"]["allowWrite"][0], str(scratch))
        text = (scratch / "srt-settings.json").read_text()
        for forbidden in (str(self.home), str(self.primary / ".git"), str(self.worktree), str(self.root / "tmp") + '"'):
            self.assertNotIn(forbidden, text)

    def test_worker_moving_main_is_refused_and_nothing_is_imported(self) -> None:
        """(c) A worker that also moves main (or any other branch): branch_import_refused, no import, no push."""
        before, pushed = self.refs(self.primary), git(self.origin, "for-each-ref", "refs/heads")

        def worker(clone: Path) -> None:
            self.commit(clone, "main", "evil")
            self.commit(clone, "feature/x")

        with self.assertRaisesRegex(ValueError, "branch_import_refused"):
            self.run_launcher(worker)
        self.assertEqual(self.refs(self.primary), before)
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads"), pushed)

    def test_committed_credential_is_refused_before_import_and_push(self) -> None:
        """A worker that commits the worker credential (or a secret pattern) cannot get it pushed to origin."""
        for secret in ("sk-worker", "ghp_" + "a" * 36, "-----BEGIN OPENSSH PRIVATE KEY-----"):
            with self.subTest(secret=secret[:8]):
                before, pushed = self.refs(self.primary), git(self.origin, "for-each-ref", "refs/heads")

                def worker(clone: Path, secret: str = secret) -> None:
                    git(clone, "checkout", "-q", "-B", "feature/x")
                    (clone / "leak.txt").write_text(f"key={secret}\n")
                    git(clone, "add", "leak.txt")
                    git(clone, "commit", "-q", "-m", "leak")

                with self.assertRaisesRegex(ValueError, "branch_import_refused.*secret"):
                    self.run_launcher(worker)
                self.assertEqual(self.refs(self.primary), before)
                self.assertEqual(git(self.origin, "for-each-ref", "refs/heads"), pushed)

    def test_binary_blob_with_worker_credential_is_refused_before_push(self) -> None:
        """A NUL-bearing blob is still a credential leak even when git log -p omits its bytes."""
        before, pushed = self.refs(self.primary), git(self.origin, "for-each-ref", "refs/heads")

        def worker(clone: Path) -> None:
            (clone / "leak.bin").write_bytes(b"\x00sk-worker\x00")
            git(clone, "add", "leak.bin")
            git(clone, "commit", "-q", "-m", "binary leak")

        with self.assertRaisesRegex(ValueError, "branch_import_refused.*secret"):
            self.run_launcher(worker)
        self.assertEqual(self.refs(self.primary), before)
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads"), pushed)

    def test_out_of_manifest_commit_is_refused_before_import(self) -> None:
        """The launcher checks the committed diff before it becomes a PR branch."""
        before, pushed = self.refs(self.primary), git(self.origin, "for-each-ref", "refs/heads")

        def worker(clone: Path) -> None:
            (clone / "allowed.txt").write_text("allowed")
            (clone / "hooks").mkdir()
            (clone / "hooks/escape.py").write_text("escape")
            git(clone, "add", "allowed.txt", "hooks/escape.py")
            git(clone, "commit", "-q", "-m", "outside manifest")

        with (
            patch.object(spawn_sandboxed_worker, "declared_manifest", return_value=["allowed.txt"]),
            self.assertRaisesRegex(ValueError, "branch_import_refused.*out_of_manifest"),
        ):
            self.run_launcher(worker)
        self.assertEqual(self.refs(self.primary), before)
        self.assertEqual(git(self.origin, "for-each-ref", "refs/heads"), pushed)

    def test_reverted_out_of_manifest_history_is_still_refused(self) -> None:
        """An out-of-scope path in an intermediate commit cannot be hidden by reverting it at the tip."""
        before = self.refs(self.primary)

        def worker(clone: Path) -> None:
            (clone / "escape.txt").write_text("out of scope")
            git(clone, "add", "escape.txt")
            git(clone, "commit", "-q", "-m", "outside")
            (clone / "escape.txt").unlink()
            (clone / "allowed.txt").write_text("allowed")
            git(clone, "add", "-A")
            git(clone, "commit", "-q", "-m", "hide outside")

        with (
            patch.object(spawn_sandboxed_worker, "declared_manifest", return_value=["allowed.txt"]),
            self.assertRaisesRegex(ValueError, "branch_import_refused.*out_of_manifest"),
        ):
            self.run_launcher(worker)
        self.assertEqual(self.refs(self.primary), before)

    def test_main_worktree_and_rewritten_history_are_refused(self) -> None:
        """A launch on main is refused up front; a worker that rewrites the branch cannot fast-forward the import."""
        with self.assertRaisesRegex(ValueError, "branch_import_refused"):
            spawn_sandboxed_worker.launch(str(self.primary), str(self.prompt), "sonnet")

        def rewrite(clone: Path) -> None:
            git(clone, "commit", "-q", "--allow-empty", "--amend", "-m", "rewritten base")

        before = self.refs(self.primary)
        with self.assertRaisesRegex(ValueError, "branch_import_refused"):
            self.run_launcher(rewrite)
        self.assertEqual(self.refs(self.primary), before)

    def test_missing_pinned_runtime_refuses_before_child_launch(self) -> None:
        """A missing pinned dependency cannot download or launch an uncontained worker."""
        with (
            patch("scripts.sandbox.containment.runtime_present", return_value=False),
            patch.object(spawn_sandboxed_worker, "worker_credential", return_value=None),
            patch.object(spawn_sandboxed_worker, "stream_child") as child,
            self.assertRaisesRegex(ValueError, "sandbox_unavailable"),
        ):
            spawn_sandboxed_worker.launch(str(self.worktree), str(self.prompt), "sonnet")
        child.assert_not_called()

    def test_missing_credential_keeps_fallback(self) -> None:
        """Until the owner provisions a worker credential the launcher refuses with its reason code."""
        (self.home / ".coderails/worker_credential").unlink()
        with self.assertRaisesRegex(ValueError, "worker_credential_missing"):
            self.run_launcher(lambda clone: None)
        self.assertEqual(self.seen, {})

    def test_worker_exit_status_is_kept_and_nothing_is_imported_on_failure(self) -> None:
        """A failed worker is a failed dispatch: its exit status is returned and its commits stay in the scratch."""
        before = self.refs(self.primary)

        def worker(clone: Path) -> int:
            self.commit(clone, "feature/x")
            return 42

        self.assertEqual(self.run_launcher(worker), 42)
        self.assertEqual(self.refs(self.primary), before)


if __name__ == "__main__":
    unittest.main()
