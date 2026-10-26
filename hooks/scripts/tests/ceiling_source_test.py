"""Claude verification-volume ceiling is counted per worktree and unit, not per branch name."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase

RUN_ALL = "python3 hooks/scripts/tests/run_all.py"
POST = "python3 scripts/post_evals.py post 5 abc123"
VALIDATE = "python3 scripts/post_evals.py validate-structure evals.json 5 abc123"


def git_out(repo: Path, *arguments: str) -> str:
    """Run git in the repository and return stripped stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True
    ).stdout.strip()


def key(repo: Path) -> str:
    """Independent oracle: sha1(realpath(common dir) + realpath(toplevel))."""
    common = os.path.realpath(repo / git_out(repo, "rev-parse", "--git-common-dir"))
    return hashlib.sha1((common + os.path.realpath(git_out(repo, "rev-parse", "--show-toplevel"))).encode()).hexdigest()


class CeilingSourceTests(HookCase):
    """The count follows the worktree through a rename and never leaks between repositories."""

    def request(self, command: str, repo: Path, **fields: object) -> dict[str, object]:
        """Build a native Bash request for the repository."""
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo), **fields}

    def counter(self, repo: Path, target: str) -> Path:
        """Return the worktree-keyed counter file."""
        return self.loop / "verification-ceiling" / f"{key(repo)}__{target}.count"

    def run_times(self, command: str, repo: Path, times: int, **fields: object) -> list[bool]:
        """Run the hook repeatedly and return each denial decision."""
        return [self.denied("verification_volume_ceiling", self.request(command, repo, **fields)) for _ in range(times)]

    def test_rename_keeps_the_count(self) -> None:
        """Negative control: a branch-name key would reset on rename and allow the third run."""
        repo = self.repository("repo", "before")
        self.assertEqual(self.run_times(RUN_ALL, repo, 2), [False, False])
        self.branch(repo, "after")
        self.assertEqual(self.run_times(RUN_ALL, repo, 1), [True])
        self.assertEqual(self.counter(repo, "run_all").read_text(encoding="utf-8").strip(), "3")

    def test_legacy_branch_count_is_carried_into_worktree_key(self) -> None:
        """An upgrade cannot grant a third full run on the same branch."""
        repo = self.repository("repo", "feature/old")
        legacy = self.loop / "verification-ceiling/feature-old__run_all.count"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("2", encoding="utf-8")
        self.assertEqual(self.run_times(RUN_ALL, repo, 1, session_id="s1"), [True])
        self.assertEqual(self.counter(repo, "run_all").read_text().strip(), "3")
        self.assertEqual(self.run_times(RUN_ALL, repo, 1, session_id="s1"), [True])
        self.assertEqual(self.counter(repo, "run_all").read_text().strip(), "4")
        self.assertEqual((self.loop / "s1/trace.jsonl").read_text().count("ceiling_legacy_migrated"), 1)

    def test_rollback_reads_continued_legacy_count(self) -> None:
        """A prior hook version must see runs charged after an upgrade."""
        repo = self.repository("repo", "feature/old")
        legacy = self.loop / "verification-ceiling/feature-old__run_all.count"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("1", encoding="utf-8")
        self.assertEqual(self.run_times(RUN_ALL, repo, 1), [False])
        self.assertEqual(legacy.read_text().strip(), "2")
        self.assertEqual(self.run_times(RUN_ALL, repo, 1), [True])
        self.assertEqual(legacy.read_text().strip(), "3")

    def test_ansi_c_shell_body_cannot_hide_full_suite(self) -> None:
        """Opaque shell forms cannot hide a full suite before its counter."""
        repo = self.repository("repo", "feature")
        for command in (
            "bash -c $'python3 hooks/scripts/tests/run_all.py'",
            "bash --rcfile /dev/null -c 'python3 hooks/scripts/tests/run_all.py'",
        ):
            with self.subTest(command=command):
                self.assertTrue(self.denied("verification_volume_ceiling", self.request(command, repo)))

    def test_same_branch_name_in_two_repositories_counts_independently(self) -> None:
        """Two repositories sharing a branch name keep separate counters."""
        first, second = self.repository("one", "unit-1"), self.repository("two", "unit-1")
        self.assertEqual(self.run_times(RUN_ALL, first, 2), [False, False])
        self.assertEqual(self.run_times(RUN_ALL, second, 2), [False, False])
        self.assertNotEqual(self.counter(first, "run_all"), self.counter(second, "run_all"))
        self.assertEqual(self.run_times(RUN_ALL, first, 1), [True])

    def test_linked_worktrees_of_one_repository_count_independently(self) -> None:
        """Same common dir, different toplevel: separate counters."""
        repo = self.repository("main-repo", "main")
        identity = ["-c", "user.name=t", "-c", "user.email=t@t.t"]
        subprocess.run(["git", "-C", str(repo), *identity, "commit", "-q", "--allow-empty", "-m", "i"], check=True)
        linked = self.directory / "linked"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "other", str(linked)], check=True)
        self.assertEqual(self.run_times(RUN_ALL, repo, 3), [False, False, True])
        self.assertEqual(self.run_times(RUN_ALL, linked, 2), [False, False])

    def test_post_and_validate_share_the_post_evals_ceiling(self) -> None:
        """The `post` ceremony is counted with validate-structure, so it is not a bypass."""
        repo = self.repository("repo", "unit-test")
        decisions = [self.denied("verification_volume_ceiling", self.request(c, repo)) for c in (VALIDATE, POST, POST)]
        self.assertEqual(decisions, [False, False, True])
        self.assertEqual(self.counter(repo, "post_evals").read_text(encoding="utf-8").strip(), "3")

    def test_wrappers_global_paths_and_codex_suite_are_counted(self) -> None:
        """Argv matching sees wrapped and absolute-path runs, and test_codex_hooks.py counts as the full suite."""
        repo = self.repository("repo", "unit-test")
        commands = [
            "env A=1 python3 /abs/hooks/scripts/tests/run_all.py",
            "bash -c 'python3 run_all.py'",
            "python3 packages/tests/test_codex_hooks.py",
        ]
        decisions = [self.denied("verification_volume_ceiling", self.request(c, repo)) for c in commands]
        self.assertEqual(decisions, [False, False, True])
        for command in ('echo "python3 run_all.py"', "cat run_all.py", "grep run_all.py hooks/hooks.json"):
            self.assertEqual(self.run_times(command, repo, 3), [False] * 3)

    def test_count_is_mirrored_into_the_matching_unit_under_the_lock(self) -> None:
        """work_units[u].verification is incremented when unit.worktree equals the toplevel; others are untouched."""
        repo = self.repository("repo", "unit-test")
        progress = self.loop / "fixture" / "s1" / "progress.json"
        progress.parent.mkdir(parents=True)
        top = os.path.realpath(git_out(repo, "rev-parse", "--show-toplevel"))
        units = {"1": {"worktree": top}, "2": {"worktree": "/elsewhere"}, "3": {}}
        state = {
            "schema_version": 3,
            "session_id": "s1",
            "loop_id": "loop1",
            "status": "in-progress",
            "work_units": units,
            "graph": {"active_wave": {"nodes": ["U3[1]"]}, "nodes": {"U3[1]": {"status": "running"}}},
        }
        progress.write_text(json.dumps(state), encoding="utf-8")
        self.environment["CLAUDE_LOOP_ID"] = "loop1"
        self.run_times(RUN_ALL, repo, 2, session_id="s1")
        self.run_times(POST, repo, 1, session_id="s1")
        data = json.loads(progress.read_text(encoding="utf-8"))["work_units"]
        self.assertEqual(data["1"]["verification"], {"run_all": 2, "post_evals": 1})
        self.assertNotIn("verification", data["2"])
        self.assertNotIn("verification", data["3"])
        self.assertFalse(Path(f"{progress}.lock").exists())

    def test_effective_directory_charges_only_the_target_worktree(self) -> None:
        """Supported cd and env directory selection share the physical target's counter."""
        origin, target = self.repository("origin", "origin"), self.repository("target space", "target")
        quoted = shlex.quote(str(target))
        for command in (f"cd {quoted} && {RUN_ALL}", f"env --chdir {quoted} {RUN_ALL}"):
            self.assertEqual(self.run_times(command, origin, 1), [False])
        self.assertEqual(self.run_times(RUN_ALL, target, 1), [True])
        self.assertEqual(self.counter(target, "run_all").read_text().strip(), "3")
        self.assertFalse(self.counter(origin, "run_all").exists())

    def test_foreign_unknown_or_ambiguous_mirror_is_not_written(self) -> None:
        """Optional mirroring requires a live owned loop and one current matching work unit."""
        repo = self.repository("repo", "unit-test")
        progress = self.loop / "fixture" / "s1" / "progress.json"
        progress.parent.mkdir(parents=True)
        self.environment["CLAUDE_LOOP_ID"] = "loop1"
        state = {
            "schema_version": 3,
            "session_id": "s1",
            "loop_id": "loop1",
            "status": "in-progress",
            "work_units": {"1": {"worktree": str(repo)}},
            "graph": {"active_wave": {"nodes": ["U3[1]"]}, "nodes": {"U3[1]": {"status": "running"}}},
        }
        variants = [
            dict(state, session_id="foreign"),
            dict(state, loop_id="foreign"),
            dict(state, graph={}),
            dict(state, status="complete"),
            dict(state, schema_version=2),
            dict(state, graph={"active_wave": {"nodes": ["U3[2]"]}, "nodes": {"U3[2]": {"status": "running"}}}),
            dict(state, graph={"active_wave": {"nodes": ["U3[1]"]}, "nodes": {"U3[1]": {"status": "pending"}}}),
            dict(state, work_units={"1": {"worktree": str(repo)}, "2": {"worktree": str(repo)}}),
        ]
        for variant in variants:
            raw = json.dumps(variant)
            progress.write_text(raw)
            self.run_times(RUN_ALL, repo, 1, session_id="s1")
            with self.subTest(variant=variant):
                self.assertEqual(progress.read_text(), raw)
        self.environment.pop("CLAUDE_LOOP_ID")
        raw = json.dumps(state)
        progress.write_text(raw)
        self.run_times(RUN_ALL, repo, 1, session_id="s1")
        self.assertEqual(progress.read_text(), raw)

    def test_missing_progress_file_does_not_affect_the_file_counter(self) -> None:
        """Without a progress file only the worktree-keyed counter applies."""
        repo = self.repository("repo", "unit-test")
        self.assertEqual(self.run_times(RUN_ALL, repo, 3, session_id="nosuch"), [False, False, True])

    def test_corrupt_progress_keeps_counter_denial(self) -> None:
        """Unreadable progress content is optional and cannot exempt the third counted run."""
        repo = self.repository("repo", "unit-test")
        progress = self.loop / "fixture/s1/progress.json"
        progress.parent.mkdir(parents=True)
        progress.write_text("{broken")
        self.environment["CLAUDE_LOOP_ID"] = "loop1"
        self.assertEqual(self.run_times(RUN_ALL, repo, 3, session_id="s1"), [False, False, True])
        self.assertEqual(progress.read_text(), "{broken")

    def test_ordinary_mirror_write_failure_keeps_counter_denial(self) -> None:
        """A real unwritable progress parent cannot suppress the existing worktree counter."""
        repo = self.repository("repo", "unit-test")
        progress = self.loop / "fixture/s1/progress.json"
        progress.parent.mkdir(parents=True)
        state = {
            "schema_version": 3,
            "session_id": "s1",
            "loop_id": "loop1",
            "status": "in-progress",
            "work_units": {"1": {"worktree": str(repo)}},
            "graph": {"active_wave": {"nodes": ["U3[1]"]}, "nodes": {"U3[1]": {"status": "running"}}},
        }
        raw = json.dumps(state)
        progress.write_text(raw)
        self.environment["CLAUDE_LOOP_ID"] = "loop1"
        progress.parent.chmod(0o500)
        try:
            self.assertEqual(self.run_times(RUN_ALL, repo, 3, session_id="s1"), [False, False, True])
            self.assertEqual(progress.read_text(), raw)
        finally:
            progress.parent.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
