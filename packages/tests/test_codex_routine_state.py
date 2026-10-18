"""Codex copies of the routine state machine: byte parity, spec parity, and the same behaviour on the Codex tree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Not importing scripts.tests.*: that would bind the root `scripts` package and break the Codex tests that need
# packages/codex/scripts under the same name.
ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
ROUTINES = ("docs-sync", "loop-retro-promotion")
GH_SHIM = '#!/bin/sh\necho "$@" >> "$GH_LOG"\n[ "$1 $2" = "pr list" ] && echo 7\nexit 0\n'


def git(cwd: Path, *args: str) -> str:
    """Run git with a fixed identity."""
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t"}
    env["GIT_COMMITTER_EMAIL"] = "t@t"
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def without_log(spec: dict[str, object]) -> dict[str, object]:
    """A spec minus its provider-specific log path."""
    return {k: v for k, v in spec.items() if k != "log"}


class ParityTests(unittest.TestCase):
    """The two provider trees ship the same scripts and equivalent specs."""

    def test_scripts_are_byte_identical_and_executable(self) -> None:
        """Both scripts are byte mirrors and the Codex copies are executable."""
        for name in ("routine_log.py", "routine_run.py"):
            with self.subTest(name=name):
                self.assertEqual((ROOT / "scripts" / name).read_bytes(), (CODEX / "scripts" / name).read_bytes())
                self.assertTrue(os.access(CODEX / "scripts" / name, os.X_OK))

    def test_specs_differ_only_in_the_log_path(self) -> None:
        """The Codex spec equals the Claude spec except for the log path under ~/.codex."""
        for routine in ROUTINES:
            with self.subTest(routine=routine):
                claude = json.loads((ROOT / f"routines/{routine}.json").read_text())
                codex = json.loads((CODEX / f"routines/{routine}.json").read_text())
                self.assertEqual(without_log(claude), without_log(codex))
                self.assertTrue((CODEX / codex["policy"]).is_file())
                if routine == "docs-sync":
                    self.assertTrue(codex["log"].startswith("~/.codex/"))
                    self.assertTrue(claude["log"].startswith("~/.claude/"))

    def test_codex_skills_call_the_script_once_and_drop_the_prose_chain(self) -> None:
        """Each Codex SKILL spells the gate chain once through routine_run.py."""
        for routine in ROUTINES:
            with self.subTest(routine=routine):
                text = (CODEX / f"skills/{routine}/SKILL.md").read_text()
                self.assertIn("scripts/routine_run.py", text)
                self.assertEqual(text.count("RR run-gate merge --"), 1)
                self.assertNotIn("$coderails-codex:post-evals", text)
                self.assertNotRegex(text, r"append (a|an) .?(abort|delivery)=")


class CodexBehaviourTests(unittest.TestCase):
    """The Codex copies run headless against real git and a fake gh."""

    def setUp(self) -> None:
        """Create a temp root with a fake gh on PATH and an isolated trace directory."""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {**os.environ, "PATH": f"{self.root / 'bin'}:{os.environ['PATH']}"}
        self.env |= {"GH_LOG": str(self.root / "gh.log"), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env["CLAUDE_AGENTIC_LOOP_DIR"] = str(self.root / "loop")
        (self.root / "bin").mkdir()
        shim = self.root / "bin/gh"
        shim.write_text(GH_SHIM)
        shim.chmod(0o755)
        self.log = self.root / "logs/run.log"

    def run_tool(self, cwd: Path, *args: str, routine: str = "docs-sync") -> subprocess.CompletedProcess[str]:
        """Run the Codex routine_run.py for docs-sync in cwd."""
        script = CODEX / "scripts/routine_run.py"
        argv = [sys.executable, str(script), "--log", str(self.log), routine, *args]
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=self.env)

    def test_invented_outcome_exits_2_and_appends_nothing(self) -> None:
        """The Codex routine_log refuses the historical invented outcome."""
        argv = [sys.executable, str(CODEX / "scripts/routine_log.py"), "emit", "--log", str(self.root / "x.jsonl")]
        argv += ["--run-id", "r", "--routine", "docs-sync", "--stage", "merge", "--outcome", "merge-blocked"]
        self.assertEqual(subprocess.run(argv, capture_output=True, text=True, env=self.env).returncode, 2)
        self.assertFalse((self.root / "x.jsonl").exists())

    def test_failed_event_write_keeps_the_stage_pending(self) -> None:
        """The independent Codex CLI refuses a failed log append without advancing or emitting half an event."""
        self.assertEqual(self.run_tool(self.root, "begin").returncode, 0)
        before = self.log.with_suffix(".jsonl").read_bytes()
        self.log.rename(self.log.with_suffix(".saved"))
        self.log.mkdir()
        result = self.run_tool(self.root, "stage", "fetch_branch")
        state = json.loads(self.log.with_suffix(".state.json").read_text())
        self.assertEqual((result.returncode, state["next"]), (2, 0))
        self.assertIn("log_unwritable", result.stderr)
        self.assertEqual(self.log.with_suffix(".jsonl").read_bytes(), before)

    def test_open_run_survives_rollover_and_rejects_foreign_routine(self) -> None:
        """Only explicit replacement closes the original id, and another routine cannot consume its state."""
        self.assertEqual(self.run_tool(self.root, "begin").returncode, 0)
        path = self.log.with_suffix(".state.json")
        state = json.loads(path.read_text())
        state["date"] = "2000-01-01"
        path.write_text(json.dumps(state))
        self.assertEqual(self.run_tool(self.root, "begin").returncode, 2)
        self.assertEqual(json.loads(path.read_text()), state)
        result = self.run_tool(self.root, "finish", "no_drift", routine="loop-retro-promotion")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("routine_mismatch", result.stderr)
        self.assertEqual(json.loads(path.read_text()), state)
        self.assertEqual(self.run_tool(self.root, "begin", "--new").returncode, 0)
        rows = [json.loads(line) for line in self.log.with_suffix(".jsonl").read_text().splitlines()]
        self.assertEqual([row["outcome"] for row in rows], ["run_incomplete", "run_abort", "run_incomplete"])
        self.assertEqual(rows[1]["run_id"], state["run_id"])
        self.assertNotEqual(rows[-1]["run_id"], state["run_id"])

    def test_no_drift_run_is_green_and_script_edit_aborts_with_one_cleanup(self) -> None:
        """A no-drift run reads green; a scripts/ edit aborts at manifest_check with one cleanup."""
        self.assertEqual(self.run_tool(self.root, "begin").returncode, 0)
        self.assertEqual(self.run_tool(self.root, "finish", "no_drift").returncode, 0)
        self.assertIn("run=ok", self.log.read_text().splitlines()[-1])
        origin, work = self.root / "origin.git", self.root / "work"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.root, "clone", "-q", str(origin), str(work))
        (work / "README.md").write_text("a\n")
        git(work, "add", ".")
        git(work, "commit", "-qm", "base")
        git(work, "push", "-q", "origin", "HEAD:main")
        git(work, "fetch", "-q", "origin")
        git(work, "remote", "set-head", "origin", "main")
        git(work, "switch", "-q", "-c", "docs/fix")
        git(work, "push", "-q", "-u", "origin", "docs/fix")
        (work / "scripts").mkdir()
        (work / "scripts/x.py").write_text("print(1)\n")
        git(work, "add", ".")
        git(work, "commit", "-qm", "edit")
        git(work, "push", "-q", "origin", "docs/fix")
        self.assertEqual(self.run_tool(work, "begin").returncode, 0)
        for stage in ("fetch_branch", "evals_frozen", "edit_made"):
            self.assertEqual(self.run_tool(work, "stage", stage).returncode, 0, stage)
        self.assertEqual(self.run_tool(work, "stage", "manifest_check").returncode, 1)
        last = json.loads(self.log.with_suffix(".jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["outcome"], last["reason_code"]), ("run_abort", "docs_sync_deny"))
        self.assertEqual((self.root / "gh.log").read_text().count("pr close 7"), 1)
        self.assertNotEqual(git(work, "ls-remote", "--heads", "origin", "docs/fix").strip(), "")
        self.assertIn("abort=docs_sync_deny", self.log.read_text().splitlines()[-1])

    def test_same_basename_gate_outside_plugin_is_refused(self) -> None:
        """A same-named script from /tmp cannot stand in for the shipped push gate."""
        origin, work = self.root / "origin.git", self.root / "work"
        git(self.root, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.root, "clone", "-q", str(origin), str(work))
        (work / "README.md").write_text("a\n")
        git(work, "add", ".")
        git(work, "commit", "-qm", "base")
        git(work, "push", "-q", "origin", "HEAD:main")
        git(work, "fetch", "-q", "origin")
        git(work, "remote", "set-head", "origin", "main")
        git(work, "switch", "-q", "-c", "docs/fix")
        git(work, "push", "-q", "-u", "origin", "docs/fix")
        self.assertEqual(self.run_tool(work, "begin").returncode, 0)
        for stage in ("fetch_branch", "evals_frozen", "edit_made", "manifest_check"):
            self.assertEqual(self.run_tool(work, "stage", stage).returncode, 0, stage)
        foreign = self.root / "push.py"
        foreign.write_text("#!/bin/sh\nexit 0\n")
        foreign.chmod(0o755)
        result = self.run_tool(work, "run-gate", "push", "--", str(foreign))
        self.assertEqual(result.returncode, 2, result.stderr)
        last = json.loads(self.log.with_suffix(".jsonl").read_text().splitlines()[-1])
        self.assertEqual((last["outcome"], last["reason_code"]), ("run_abort", "gate_argv_not_allowed"))
        self.assertNotEqual(git(work, "ls-remote", "--heads", "origin", "docs/fix").strip(), "")


if __name__ == "__main__":
    unittest.main()
