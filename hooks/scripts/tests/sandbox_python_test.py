"""Check sandbox policy substitution and the launcher's clone, scrub, import and push flow without launching srt."""

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
from scripts.sandbox import render_settings, sandbox_probe, spawn_sandboxed_worker

PARENT_SECRETS = {"GH_TOKEN": "parent-gh", "GITHUB_TOKEN": "parent-github", "ANTHROPIC_API_KEY": "parent-key"}


class SandboxPythonTests(unittest.TestCase):
    """Preserve allow-only policy, scratch-only writes and pre-launch refusal."""

    def test_json_paths_and_denies(self) -> None:
        """Path punctuation stays data; only the per-worker scratch (and its provider state slug) is writable."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            scratch = root / "scratch"
            workdir = scratch / 'clone|"\\tree'
            home = root / "home"
            workdir.mkdir(parents=True)
            home.mkdir()
            output = root / "settings.json"
            with (
                patch.dict(os.environ, {"HOME": str(home), "TMPDIR": str(scratch) + "/"}),
                patch.object(shutil, "which", return_value="/fixture/rg"),
            ):
                render_settings.render_settings(str(workdir), str(scratch), str(output))
            data = json.loads(output.read_text())
            state = Path(f"/private/tmp/claude-{os.getuid()}") / str(workdir).replace("/", "-")
            self.assertEqual(data["filesystem"]["allowWrite"], [str(scratch), str(state)])
            self.assertEqual(data["filesystem"]["denyRead"], [])
            self.assertNotIn("*", data["network"]["allowedDomains"])
            state.rmdir()

    def test_bad_input_never_writes_policy(self) -> None:
        """Refuse missing or relative paths before creating a settings file."""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "settings.json"
            with self.assertRaises(ValueError):
                render_settings.render_settings("relative", temporary, str(output))
            self.assertFalse(output.exists())

    def test_guard_denial_precedes_scratch(self) -> None:
        """A denied native worker cannot allocate scratch or call npx."""
        with tempfile.TemporaryDirectory() as temporary:
            prompt = Path(temporary) / "prompt"
            prompt.write_text("worker instructions")
            denial = subprocess.CompletedProcess(
                ["python"],
                0,
                '{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"freeze required"}}',
                "",
            )
            with (
                patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "session"}),
                patch.object(subprocess, "run", return_value=denial) as run,
                patch.object(tempfile, "mkdtemp") as scratch,
                patch.object(Path, "is_file", return_value=True),
            ):
                with self.assertRaisesRegex(ValueError, "freeze required"):
                    spawn_sandboxed_worker.launch(temporary, str(prompt), "sonnet")
                self.assertEqual(run.call_count, 1)
                scratch.assert_not_called()
                payload = json.loads(run.call_args.kwargs["input"])
                self.assertIn("spawn_sandboxed_worker.py", payload["tool_input"]["command"])

    def test_bare_probe_rejects_successful_escape(self) -> None:
        """Outside writes distinguish an uncontained probe from real enforcement."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            root = Path(temporary)
            worktree = root / "repo"
            home = root / "home"
            worktree.mkdir()
            home.mkdir()
            subprocess.run(["git", "init", "-q", str(worktree)], check=True)
            (home / ".claude.json").write_text("{}")
            with patch.dict(os.environ, {"HOME": str(home), "GH_TOKEN": "leaked"}):
                self.assertEqual(sandbox_probe.probe(worktree), 2)
            self.assertEqual((home / ".claude.json").read_text(), "{}")
            self.assertFalse((home / ".sandbox-escape-probe").exists())
            self.assertFalse((root / "escape-probe").exists())
            inside = worktree / ".sandbox-probe"

            def only_inside(path: Path) -> bool:
                return path == inside

            with (
                patch.dict(os.environ, {"HOME": str(home)}, clear=False),
                patch.object(sandbox_probe, "probe_write", side_effect=only_inside),
            ):
                os.environ.pop("GH_TOKEN", None)
                self.assertEqual(sandbox_probe.probe(worktree), 0)


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
            "ANTHROPIC_API_KEY",
        }
        self.assertLessEqual(set(env), allowed)
        self.assertEqual(env["ANTHROPIC_API_KEY"], "sk-worker")
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
