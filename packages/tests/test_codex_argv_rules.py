"""Codex side of the argv classifier: byte parity with Claude, test gate, destructive gate, ceiling, policy file."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "packages/codex"
HOOKS = PACKAGE / "hooks/scripts"
MIRRORED = (
    "hooks/scripts/lib/argv_match.py",
    "hooks/scripts/lib/protected_paths.py",
    "hooks/scripts/lib/ceiling_key.py",
    "policy/protected_paths.json",
)
RUN_ALL = "python3 packages/tests/test_codex_hooks.py"
POST = "python3 scripts/post_evals.py post 5 abc123"
sys.path.insert(0, str(HOOKS))
from lib import ceiling_key  # noqa: E402 - needs the hooks directory on the path first


def git(repo: Path, *arguments: str) -> str:
    """Run git in the repository and return stripped stdout."""
    done = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True)
    return done.stdout.strip()


class ParityTests(unittest.TestCase):
    """The shared classifier, policy loader and policy file are byte-identical across providers."""

    def test_mirrored_files_are_byte_identical(self) -> None:
        """Acceptance 7."""
        for relative in MIRRORED:
            with self.subTest(file=relative):
                self.assertEqual((ROOT / relative).read_bytes(), (PACKAGE / relative).read_bytes())


class CodexHookCase(unittest.TestCase):
    """Run the real Codex hooks against throwaway repositories."""

    def setUp(self) -> None:
        """Create isolated Git, plugin data and loop roots, and a private hook copy for policy edits."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.data = self.directory / "data"
        self.loop = self.directory / "loops"
        self.environment = os.environ | {
            "HOME": str(self.directory / "home"),
            "PLUGIN_ROOT": str(PACKAGE),
            "PLUGIN_DATA": str(self.data),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.loop),
            "CODERAILS_TEST_OUTPUT_DIR": str(self.directory / "logs"),
        }
        self.repo = self.repository("repo", "feature/test")

    def repository(self, name: str, branch: str) -> Path:
        """Create an uncommitted repository on a named branch."""
        path = self.directory / name
        path.mkdir()
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True)
        return path

    def hook(self, name: str, payload: dict[str, Any], scripts: Path = HOOKS) -> dict[str, Any]:
        """Execute one hook and return its parsed output."""
        done = subprocess.run(
            [sys.executable, str(scripts / f"{name}.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.environment,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else {}

    def bash(self, name: str, command: str, repo: Path | None = None, scripts: Path = HOOKS) -> bool:
        """Return whether the hook denied the Bash command."""
        payload = {"session_id": "s1", "cwd": str(repo or self.repo), "tool_input": {"command": command}}
        return bool(self.hook(name, payload, scripts).get("hookSpecificOutput", {}).get("permissionDecision") == "deny")


class TestGateTests(CodexHookCase):
    """Acceptance 1 and 2 on the Codex test gate."""

    def test_commit_forms_deny_and_other_commands_do_not(self) -> None:
        """Every commit form denies a failing project test command; quoted text and other subcommands do not."""
        trusted = self.repo / ".git/coderails/test_command"
        trusted.parent.mkdir(parents=True, exist_ok=True)
        trusted.write_text("false\n", encoding="utf-8")
        denied = [
            "command -p git commit -m x",
            "sudo -n git commit -m x",
            "{ git commit -m x; }",
            "if true; then git commit -m x; fi",
            "timeout 60 git commit -m x",
            "2>&1 git commit -m x",
            "bash -c 'git commit -m x' # \"",
            "git -C /r commit -m x",
            "git -c user.name=x commit -m x",
            "/usr/bin/git commit -m x",
            "env A=1 git -C d commit",
            "bash -c 'git -C d commit -m x'",
            'git commit -m "unbalanced',
        ]
        for command in denied:
            with self.subTest(command=command):
                self.assertTrue(self.bash("test_gate", command))
        for command in ('echo "git commit"', "git log --grep commit", 'echo "unbalanced git commit'):
            with self.subTest(command=command):
                self.assertFalse(self.bash("test_gate", command))


class DestructiveTests(CodexHookCase):
    """Acceptance 3 on the Codex destructive gate."""

    def test_no_verify_forms_are_denied(self) -> None:
        """--no-verify and -n are denied behind global options; ordinary commits and quoted text are not."""
        denied = (
            "git commit --no-verif -m x",
            "git -C d commit --no-ver",
            "git -C d commit --no-verify",
            "git commit -n",
            "git -c a=b commit -nm x",
            "env A=1 git commit -n",
        )
        for command in denied:
            with self.subTest(command=command):
                self.assertTrue(self.bash("destructive_bash_gate", command))
        for command in ("git commit -m x", "git -C d commit -m x", 'echo "git commit -n"', "git commit -m -n"):
            with self.subTest(command=command):
                self.assertFalse(self.bash("destructive_bash_gate", command))


class CeilingTests(CodexHookCase):
    """Acceptance 5 on the Codex ceiling."""

    def key(self, repo: Path) -> str:
        """Independent oracle for the worktree key."""
        common = os.path.realpath(repo / git(repo, "rev-parse", "--git-common-dir"))
        return hashlib.sha1((common + os.path.realpath(git(repo, "rev-parse", "--show-toplevel"))).encode()).hexdigest()

    def runs(self, command: str, repo: Path, times: int) -> list[bool]:
        """Run the ceiling hook repeatedly."""
        return [self.bash("verification_volume_ceiling", command, repo) for _ in range(times)]

    def test_rename_and_two_repositories(self) -> None:
        """A rename keeps the count; a second repository with the same branch name starts at zero."""
        self.assertEqual(self.runs(RUN_ALL, self.repo, 2), [False, False])
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/renamed"], check=True)
        self.assertEqual(self.runs(RUN_ALL, self.repo, 1), [True])
        twin = self.repository("twin", "renamed")
        self.assertEqual(self.runs(RUN_ALL, twin, 2), [False, False])
        counter = self.data / "verification-ceiling" / f"{self.key(self.repo)}__full-suite.count"
        self.assertEqual(counter.read_text(encoding="utf-8").strip(), "3")

    def test_post_counts_with_validate_structure(self) -> None:
        """The `post` ceremony shares the eval-ceremony ceiling."""
        validate = "python3 scripts/post_evals.py validate-structure e.json 5 abc"
        decisions = [self.bash("verification_volume_ceiling", c, self.repo) for c in (validate, POST, POST)]
        self.assertEqual(decisions, [False, False, True])

    def test_operation_mentions_do_not_consume_the_ceiling(self) -> None:
        """A body path called post cannot exhaust the actual post ceremony's allowance."""
        mention = "python3 scripts/post_evals.py validate-embed evals.json post"
        self.assertEqual(self.runs(mention, self.repo, 3), [False] * 3)
        leading = "python3 scripts/post_evals.py --progress=p post 5 evals.json"
        self.assertEqual(self.runs(leading, self.repo, 3), [False, False, True])

    def test_wrapped_runs_count_and_mentions_do_not(self) -> None:
        """Argv matching counts wrapped runs and ignores quoted or non-executing mentions."""
        wrapped = ["env A=1 python3 /abs/hooks/scripts/tests/run_all.py", "bash -c 'python3 run_all.py'", RUN_ALL]
        decisions = [self.bash("verification_volume_ceiling", c, self.repo) for c in wrapped]
        self.assertEqual(decisions, [False, False, True])
        for command in ('echo "python3 run_all.py"', "cat run_all.py"):
            self.assertEqual(self.runs(command, self.repo, 3), [False] * 3)

    def test_count_is_mirrored_into_the_matching_unit(self) -> None:
        """work_units[u].verification is incremented under lock only for the unit whose worktree matches."""
        progress = self.loop / "fixture" / "s1" / "progress.json"
        progress.parent.mkdir(parents=True)
        top = ceiling_key.worktree_key(str(self.repo))[1]
        units = {"1": {"worktree": top}, "2": {"worktree": "/elsewhere"}}
        progress.write_text(json.dumps({"work_units": units}), encoding="utf-8")
        self.runs(RUN_ALL, self.repo, 2)
        self.runs(POST, self.repo, 1)
        data = json.loads(progress.read_text(encoding="utf-8"))["work_units"]
        self.assertEqual(data["1"]["verification"], {"run_all": 2, "post_evals": 1})
        self.assertNotIn("verification", data["2"])


class ProtectedPathsTests(CodexHookCase):
    """Acceptance 6 on the Codex hooks, from a private copy of the package whose JSON the test edits."""

    def setUp(self) -> None:
        """Copy hooks/ and policy/, and put the repository on main."""
        super().setUp()
        self.plugin = self.directory / "plugin"
        shutil.copytree(PACKAGE / "hooks", self.plugin / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        shutil.copytree(PACKAGE / "policy", self.plugin / "policy")
        self.policy = self.plugin / "policy/protected_paths.json"
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

    def edit_policy(self, key: str, change: Callable[[list[str]], list[str]]) -> None:
        """Replace one list in the private policy copy."""
        data = json.loads(self.policy.read_text())
        data[key] = change(data[key])
        self.policy.write_text(json.dumps(data), encoding="utf-8")

    def sed(self, target: str) -> str:
        """Return the destructive gate's denial reason for an in-place sed edit, or an empty string."""
        payload = {"cwd": str(self.repo), "tool_input": {"command": f"sed -i s/a/b/ {target}"}}
        output = self.hook("destructive_bash_gate", payload, self.plugin / "hooks/scripts")
        return str(output.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))

    def patch(self, target: str) -> str:
        """Return the edit-on-main denial reason for a patch touching the target, or an empty string."""
        text = f"*** Begin Patch\n*** Update File: {target}\n@@\n-a\n+b\n*** End Patch\n"
        payload = {"cwd": str(self.repo), "tool_name": "apply_patch", "tool_input": {"command": text}}
        output = self.hook("no_edit_on_main", payload, self.plugin / "hooks/scripts")
        return str(output.get("hookSpecificOutput", {}).get("permissionDecisionReason", ""))

    def test_adding_an_extension_changes_both_gates_without_code_change(self) -> None:
        """Negative control: .rs is not a source extension until the JSON says so; edits follow doc_extensions."""
        self.assertEqual(self.sed("x.rs"), "")
        self.edit_policy("source_extensions", lambda values: [*values, ".rs"])
        self.assertIn("source edit on main", self.sed("x.rs"))
        self.assertIn("Blocked edit", self.patch("x.rs"))
        self.assertEqual(self.patch("README.md"), "")
        self.edit_policy("doc_extensions", lambda values: [v for v in values if v != ".md"])
        self.assertIn("Blocked edit", self.patch("README.md"))

    def test_the_policy_file_cannot_be_edited_on_main(self) -> None:
        """Negative control: another .json is a document; the policy file itself is not."""
        self.assertEqual(self.patch("config/other.json"), "")
        (self.repo / "policy/nested").mkdir(parents=True)
        for target in (
            "policy/protected_paths.json",
            "policy/./protected_paths.json",
            "policy//protected_paths.json",
            "policy/nested/../protected_paths.json",
            f"{self.repo}/policy/./protected_paths.json",
        ):
            with self.subTest(target=target):
                self.assertIn("Blocked edit", self.patch(target))

    def test_deleted_policy_fails_closed_on_main(self) -> None:
        """A missing file denies with protected_paths_unreadable on main and not on a feature branch."""
        self.policy.unlink()
        self.assertIn("protected_paths_unreadable", self.sed("x.py"))
        self.assertIn("protected_paths_unreadable", self.patch("README.md"))
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature"], check=True)
        self.assertEqual(self.patch("README.md"), "")


if __name__ == "__main__":
    unittest.main()
