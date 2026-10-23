"""routine_run.py: one state machine for both routines, headless (no hooks), real git and a fake gh shim."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GH_SHIM = (REPO / "scripts/tests/fixtures/routine_gh.sh").read_text()
STAGES = ("fetch_branch", "evals_frozen", "edit_made", "manifest_check", "push", "review")
LATER = ("post_review", "post_evals", "merge")
BRANCH = "docs/fix"


def git(cwd: Path, *args: str) -> str:
    """Run git in a temp repo with a fixed identity."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def last_marker_is_green(log: Path) -> bool:
    """The dashboard's last-marker predicate from examples/dashboard-config.json: last of run=ok|abort=|refused=."""
    found = None
    for line in log.read_text().splitlines():
        if "run=ok" in line:
            found = True
        elif "abort=" in line or "refused=" in line:
            found = False
    return found is True


class RoutineCase(unittest.TestCase):
    """A bare origin, a work clone with a pushed feature branch, a fake gh and per-test logs."""

    routine = "docs-sync"
    script = REPO / "scripts" / "routine_run.py"
    base_files = {
        "README.md": "a\n",
        "scripts/gate.sh": "echo\n",
        "skills/agentic-loop/learned-failure-modes.md": "m\n",
    }

    def setUp(self) -> None:
        """Build origin, clone, base commit, feature branch, gh shim and log paths."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.work, self.origin, self.bin = root / "work", root / "origin.git", root / "bin"
        self.plugin = root / "plugin"
        shutil.copytree(
            REPO / "scripts",
            self.plugin / "scripts",
            ignore=shutil.ignore_patterns("tests", "__pycache__"),
        )
        shutil.copytree(REPO / "routines", self.plugin / "routines")
        shutil.copytree(REPO / "policy", self.plugin / "policy")
        shutil.copytree(REPO / "hooks" / "scripts" / "lib", self.plugin / "hooks" / "scripts" / "lib")
        self.script = self.plugin / "scripts" / "routine_run.py"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(root, "clone", "-q", str(self.origin), str(self.work))
        for name, text in self.base_files.items():
            self.write(name, text)
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", "base")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        git(self.work, "fetch", "-q", "origin")
        git(self.work, "remote", "set-head", "origin", "main")
        git(self.work, "switch", "-q", "-c", BRANCH)
        self.bin.mkdir()
        shim = self.bin / "gh"
        shim.write_text(GH_SHIM)
        shim.chmod(0o755)
        for name in ("push", "post_review", "post_evals", "merge"):
            gate = self.plugin / "scripts" / f"{name}.py"
            gate.write_text(
                "#!/usr/bin/env python3\nimport pathlib, sys\n"
                "(pathlib.Path(__file__).parent / 'ran').open('a').write('ran\\n')\n"
                "raise SystemExit(1 if len(sys.argv) > 1 and sys.argv[1] == '1' else 0)\n"
            )
            gate.chmod(0o755)
        self.ran = self.plugin / "scripts" / "ran"
        self.remote_branch_pushed = False
        self.gh_log = root / "gh.log"
        self.log = root / "logs" / "run.log"
        self.jsonl = self.log.with_suffix(".jsonl")

    def write(self, name: str, text: str) -> None:
        """Write a file in the work tree."""
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message: str = "edit") -> None:
        """Commit everything and push the feature branch."""
        git(self.work, "add", "-A")
        git(self.work, "commit", "-qm", message)
        git(self.work, "push", "-q", "origin", BRANCH)
        self.remote_branch_pushed = True

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run routine_run.py for this routine in the work tree with the shim on PATH."""
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "GH_LOG": str(self.gh_log)}
        env |= {"CLAUDE_AGENTIC_LOOP_DIR": str(Path(self.tmp.name) / "loop"), "PYTHONDONTWRITEBYTECODE": "1"}
        argv = [sys.executable, str(self.script), "--log", str(self.log), self.routine, *args]
        return subprocess.run(argv, cwd=self.work, capture_output=True, text=True, env=env)

    def rows(self) -> list[dict[str, str]]:
        """The JSONL event rows written so far."""
        return [json.loads(x) for x in self.jsonl.read_text().splitlines()] if self.jsonl.exists() else []

    def gh_calls(self) -> list[str]:
        """The argument lines the fake gh recorded."""
        return self.gh_log.read_text().splitlines() if self.gh_log.exists() else []

    def stage(self, name: str) -> subprocess.CompletedProcess[str]:
        """Perform a stage: gates through run-gate with `true`, the rest through stage."""
        gates = ("push", *LATER)
        if name in gates:
            args = ("7",) if name == "merge" else ()
            return self.run_tool("run-gate", name, "--", str(self.plugin / "scripts" / f"{name}.py"), *args)
        return self.run_tool("stage", name)

    def advance_to_manifest_check(self) -> subprocess.CompletedProcess[str]:
        """Begin, perform the first three stages, then run manifest_check and return its result."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        for name in STAGES[:3]:
            self.assertEqual(self.stage(name).returncode, 0, name)
        return self.run_tool("stage", "manifest_check")

    def assert_cleaned_once(self) -> None:
        """PR close and local cleanup run once; remote branch stays and no run_ok row is emitted."""
        self.assertEqual([c for c in self.gh_calls() if c.startswith("pr close")], ["pr close 7"])
        remote = git(self.work, "ls-remote", "--heads", "origin", BRANCH).strip()
        self.assertEqual(bool(remote), self.remote_branch_pushed)
        self.assertEqual(git(self.work, "branch", "--list", BRANCH).strip(), "")
        self.assertNotIn("run_ok", [r["outcome"] for r in self.rows()])


class DocsSyncRunTests(RoutineCase):
    """The docs-sync spec and policy."""

    def test_full_run_reads_green_and_killed_run_reads_red(self) -> None:
        """begin, nine stages in order, finish ok: last marker green. Ending after begin: red, and distinguishable."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        for name in STAGES[4:] + LATER:
            self.assertEqual(self.stage(name).returncode, 0, name)
        self.assertEqual(self.run_tool("finish", "ok").returncode, 0)
        self.assertEqual(self.rows()[-1]["outcome"], "run_ok")
        self.assertTrue(last_marker_is_green(self.log))
        self.assertEqual([call for call in self.gh_calls() if not call.startswith("pr view")], [])
        # killed: a later run on the same log that ends after begin leaves the provisional row standing
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertFalse(last_marker_is_green(self.log))
        self.assertEqual(self.rows()[-1]["outcome"], "run_incomplete")

    def test_killed_run_differs_from_never_started(self) -> None:
        """Negative control: the old text marker reading of an empty log and a killed log both lack a terminal."""
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.run_tool("begin").returncode, 0)
        rows = self.rows()
        self.assertEqual([r["outcome"] for r in rows], ["run_incomplete"])
        self.assertEqual(rows[0]["reason_code"], "incomplete-run")
        self.assertFalse(last_marker_is_green(self.log))

    def test_no_drift_finish(self) -> None:
        """A no-drift night is begin then finish no_drift; run_ok is derived and delivery never started."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertEqual(self.run_tool("finish", "no_drift").returncode, 0)
        self.assertTrue(last_marker_is_green(self.log))

    def test_script_edit_aborts_once_with_cleanup(self) -> None:
        """A diff touching scripts/x.py aborts, closes the PR and cleans up the local branch once."""
        self.write("scripts/x.py", "print(1)\n")
        self.commit()
        result = self.advance_to_manifest_check()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        last = self.rows()[-1]
        self.assertEqual((last["outcome"], last["reason_code"]), ("run_abort", "docs_sync_deny"))
        self.assertFalse(last_marker_is_green(self.log))
        self.assert_cleaned_once()
        self.assertEqual(self.run_tool("abort", "audit_failed").returncode, 2)  # already terminal: no second cleanup
        self.assert_cleaned_once()

    def test_rename_into_md_aborts_via_docs_sync_deny(self) -> None:
        """A git mv of scripts/gate.sh to evil.md is a rename whose source is out of scope."""
        git(self.work, "mv", "scripts/gate.sh", "evil.md")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 1)
        self.assertEqual(self.rows()[-1]["reason_code"], "docs_sync_deny")
        self.assert_cleaned_once()

    def test_run_gate_nonzero_is_refusal_for_that_gate(self) -> None:
        """A gate command exiting 1 records run_refused gate=merge, never run_ok, and cleans up."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        for name in STAGES[4:] + LATER[:-1]:
            self.assertEqual(self.stage(name).returncode, 0, name)
        result = self.run_tool("run-gate", "merge", "--", str(self.plugin / "scripts/merge.py"), "1")
        self.assertNotEqual(result.returncode, 0)
        last = self.rows()[-1]
        self.assertEqual((last["outcome"], last["reason_code"], last["stage"]), ("run_refused", "merge", "merge"))
        self.assertIn("refused=merge", self.log.read_text())
        self.assert_cleaned_once()

    def test_push_before_manifest_check_is_out_of_order(self) -> None:
        """Negative control: the gate command is not run and the run aborts stage_out_of_order."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        for name in STAGES[:3]:
            self.assertEqual(self.stage(name).returncode, 0)
        result = self.run_tool("run-gate", "push", "--", str(self.bin / "push.py"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("stage_out_of_order", result.stderr)
        self.assertFalse(self.ran.exists())
        self.assertEqual(self.rows()[-1]["reason_code"], "stage_out_of_order")
        self.assert_cleaned_once()

    def test_finish_ok_before_all_stages_is_out_of_order(self) -> None:
        """Finish ok cannot skip the delivery stages."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertEqual(self.stage("fetch_branch").returncode, 0)
        self.assertEqual(self.run_tool("finish", "ok").returncode, 2)
        self.assertNotIn("run_ok", [r["outcome"] for r in self.rows()])

    def test_cleanup_refuses_after_branch_switch(self) -> None:
        """An abort from a different branch leaves the run branch and PR untouched."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertEqual(self.run_tool("stage", "fetch_branch").returncode, 0)
        git(self.work, "switch", "-q", "main")
        self.assertEqual(self.run_tool("abort", "audit_failed").returncode, 0)
        self.assertNotIn("pr close 7", self.gh_calls())
        self.assertNotEqual(git(self.work, "branch", "--list", BRANCH).strip(), "")
        self.assertNotEqual(git(self.work, "ls-remote", "--heads", "origin", "main").strip(), "")

    def test_run_gate_pins_the_script_per_stage(self) -> None:
        """Negative control: a no-op argv for a gate, or any argv for a non-gate stage, aborts and runs nothing."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        foreign = self.bin / "push.py"
        foreign.write_text("#!/bin/sh\nexit 0\n")
        foreign.chmod(0o755)
        result = self.run_tool("run-gate", "push", "--", str(foreign))
        self.assertEqual(result.returncode, 2)
        self.assertIn("gate_argv_not_allowed", result.stderr)
        self.assertEqual(self.rows()[-1]["reason_code"], "gate_argv_not_allowed")
        self.assert_cleaned_once()

    def test_run_gate_rejects_non_gate_stage(self) -> None:
        """run-gate manifest_check -- true cannot stand in for the policy check."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        for name in STAGES[:3]:
            self.assertEqual(self.stage(name).returncode, 0, name)
        self.assertEqual(self.run_tool("run-gate", "manifest_check", "--", "true").returncode, 2)
        self.assertEqual(self.rows()[-1]["reason_code"], "gate_argv_not_allowed")
        self.assertFalse(last_marker_is_green(self.log))

    def test_documented_python3_form_of_the_pinned_script_is_allowed(self) -> None:
        """The configured plugin script passes under the documented python3 command."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        script = str(self.plugin / "scripts/push.py")
        result = self.run_tool("run-gate", "push", "--", "python3", script)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_uncommitted_edit_fails_manifest_check(self) -> None:
        """An edit left uncommitted at manifest_check is not an empty diff."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.write("scripts/x.py", "print(1)\n")
        self.assertEqual(self.advance_to_manifest_check().returncode, 1)
        self.assertEqual(self.rows()[-1]["reason_code"], "dirty_worktree")
        self.assert_cleaned_once()

    def test_edit_between_manifest_check_and_push_is_rechecked(self) -> None:
        """The manifest runs again inside run-gate push, before the gate command."""
        self.write("docs/a.md", "x\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)
        self.write("scripts/x.py", "print(1)\n")
        self.commit("late edit")
        self.assertEqual(
            self.run_tool("run-gate", "push", "--", str(self.plugin / "scripts/push.py")).returncode,
            1,
        )
        self.assertEqual(self.rows()[-1]["reason_code"], "docs_sync_deny")
        self.assertFalse(self.ran.exists())
        self.assert_cleaned_once()

    def test_stray_brace_in_log_does_not_crash(self) -> None:
        """A {bad} placeholder in --log is literal text, not a KeyError."""
        self.log = Path(self.tmp.name) / "{bad}" / "run.log"
        self.jsonl = self.log.with_suffix(".jsonl")
        result = self.run_tool("begin")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_begin_cannot_launder_a_failed_or_open_run(self) -> None:
        """Begin is refused while a run is open or after a same-day abort, unless --new."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertEqual(self.run_tool("begin").returncode, 2)
        self.assertEqual(self.run_tool("abort", "audit_failed").returncode, 0)
        self.assertEqual(self.run_tool("begin").returncode, 2)
        self.assertEqual(self.run_tool("begin", "--new").returncode, 0)

    def test_log_failure_does_not_advance_or_leave_an_unpaired_row(self) -> None:
        """A failed human-log append must leave the stage pending and both event logs unchanged."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        before = self.jsonl.read_bytes()
        self.log.rename(self.log.with_suffix(".saved"))
        self.log.mkdir()
        result = self.stage("fetch_branch")
        state = json.loads(self.log.with_suffix(".state.json").read_text())
        self.assertEqual((result.returncode, state["next"], self.jsonl.read_bytes()), (2, 0, before))
        self.assertIn("log_unwritable", result.stderr)

    def test_foreign_routine_cannot_finish_another_routines_state(self) -> None:
        """Sharing a log path does not authorize the other routine to finish or replace active state."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        state = self.log.with_suffix(".state.json")
        before = (state.read_bytes(), self.jsonl.read_bytes(), self.log.read_bytes())
        self.routine = "loop-retro-promotion"
        for args in (("finish", "no_drift"), ("begin", "--new")):
            result = self.run_tool(*args)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("routine_mismatch", result.stderr)
            self.assertEqual((state.read_bytes(), self.jsonl.read_bytes(), self.log.read_bytes()), before)

    def test_old_open_run_is_not_overwritten_at_date_rollover(self) -> None:
        """An open run from yesterday remains active until explicitly ended or replaced."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        path = self.log.with_suffix(".state.json")
        state = json.loads(path.read_text())
        state["date"] = "2000-01-01"
        path.write_text(json.dumps(state))
        result = self.run_tool("begin")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(path.read_text()), state)

    def test_explicit_new_begin_closes_the_previous_open_run(self) -> None:
        """Explicit replacement leaves one abort for the previous id before the next provisional row."""
        self.assertEqual(self.run_tool("begin").returncode, 0)
        previous = self.rows()[0]["run_id"]
        self.assertEqual(self.run_tool("begin", "--new").returncode, 0)
        self.assertEqual([r["outcome"] for r in self.rows()], ["run_incomplete", "run_abort", "run_incomplete"])
        self.assertEqual(self.rows()[1]["run_id"], previous)
        self.assertEqual(self.rows()[1]["reason_code"], "incomplete-run")
        self.assertNotEqual(self.rows()[-1]["run_id"], previous)

    def test_new_dated_run_uses_todays_log_after_loading_old_state(self) -> None:
        """Loading a completed previous day's pinned path must not redirect the next run to that old log."""
        self.log = Path(self.tmp.name) / "run-{date}.log"
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertEqual(self.run_tool("finish", "no_drift").returncode, 0)
        path = self.log.with_name("run-active.state.json")
        state = json.loads(path.read_text())
        expected_human = state["human"]
        state["date"], state["human"] = "2000-01-01", str(self.log.with_name("run-2000-01-01.log"))
        path.write_text(json.dumps(state))
        self.assertEqual(self.run_tool("begin").returncode, 0)
        self.assertEqual(json.loads(path.read_text())["human"], expected_human)
        self.assertIn("abort=incomplete-run", Path(expected_human).read_text().splitlines()[-1])


class RetroPromotionRunTests(RoutineCase):
    """The loop-retro-promotion spec and its one-path policy."""

    routine = "loop-retro-promotion"

    def test_second_path_is_refused(self) -> None:
        """The one-path policy refuses a second changed path (too_many_paths) and the run aborts with cleanup."""
        self.write("skills/agentic-loop/learned-failure-modes.md", "m2\n")
        self.write("other.md", "o\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 1)
        self.assertEqual(self.rows()[-1]["reason_code"], "too_many_paths")
        self.assert_cleaned_once()

    def test_single_modification_passes(self) -> None:
        """The permitted lone M passes the manifest check."""
        self.write("skills/agentic-loop/learned-failure-modes.md", "m2\n")
        self.commit()
        self.assertEqual(self.advance_to_manifest_check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
