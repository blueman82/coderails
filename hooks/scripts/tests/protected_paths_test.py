"""policy/protected_paths.json drives the source-write and edit-on-main gates with no code change."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import protected_paths

ROOT = Path(__file__).resolve().parents[3]


class LoaderTests(unittest.TestCase):
    """The loader returns the shipped policy and refuses anything torn or ill-shaped."""

    def test_shipped_policy_loads(self) -> None:
        """The shipped file has all five keys with the historical values."""
        data = protected_paths.load()
        self.assertEqual(sorted(data), sorted(protected_paths.KEYS))
        self.assertIn(".py", data["source_extensions"])
        self.assertIn(".md", data["doc_extensions"])

    def test_missing_torn_and_ill_shaped_files_raise_the_reason_code(self) -> None:
        """Every unreadable form raises protected_paths_unreadable."""
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            good = json.loads((ROOT / "policy/protected_paths.json").read_text())
            cases = {
                "torn.json": "{not json",
                "list.json": "[]",
                "missing_key.json": json.dumps({k: v for k, v in good.items() if k != "doc_names"}),
                "bad_type.json": json.dumps({**good, "doc_names": "LICENSE"}),
                "bad_extension.json": json.dumps({**good, "source_extensions": ["py"]}),
            }
            for name, text in cases.items():
                (base / name).write_text(text, encoding="utf-8")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "protected_paths_unreadable"):
                    protected_paths.load(base / name)
            with self.assertRaisesRegex(ValueError, "protected_paths_unreadable"):
                protected_paths.load(base / "absent.json")


class PolicyDrivenHookTests(unittest.TestCase):
    """Run the real hooks from a private copy of hooks/ and policy/ whose JSON the test edits."""

    def setUp(self) -> None:
        """Copy the hook tree, create a repository on main, and isolate logs."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.plugin = self.directory / "plugin"
        shutil.copytree(ROOT / "hooks", self.plugin / "hooks", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        shutil.copytree(ROOT / "policy", self.plugin / "policy")
        self.policy = self.plugin / "policy/protected_paths.json"
        self.repo = self.directory / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/main"], check=True)

    def edit_policy(self, key: str, value: list[str]) -> None:
        """Replace one list in the private policy copy."""
        data = json.loads(self.policy.read_text())
        data[key] = value
        self.policy.write_text(json.dumps(data), encoding="utf-8")

    def run_hook(self, name: str, tool_input: dict[str, str]) -> str:
        """Return the denial reason from the private hook copy, or an empty string when allowed."""
        payload = {"tool_name": "Bash", "cwd": str(self.repo), "tool_input": tool_input}
        done = subprocess.run(
            [sys.executable, str(self.plugin / f"hooks/scripts/{name}.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "HOME": str(self.directory), "CLAUDE_DISCIPLINE_LOG": f"{self.directory}/l"},
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        output: dict[str, Any] = json.loads(done.stdout)["hookSpecificOutput"] if done.stdout.strip() else {}
        return str(output.get("permissionDecisionReason", "")) if output.get("permissionDecision") == "deny" else ""

    def sed(self, target: str) -> str:
        """Run the destructive gate on an in-place sed edit of the target."""
        return self.run_hook("destructive_bash_gate", {"command": f"sed -i s/a/b/ {target}"})

    def edit(self, target: str) -> str:
        """Run the edit-on-main gate on an Edit of the target."""
        return self.run_hook("no_edit_on_main", {"file_path": target})

    def test_adding_an_extension_to_the_json_protects_it_without_code_change(self) -> None:
        """Negative control: .rs is absent so sed -i is allowed; adding it denies the same command."""
        self.assertEqual(self.sed("x.rs"), "")
        self.edit_policy("source_extensions", [*json.loads(self.policy.read_text())["source_extensions"], ".rs"])
        self.assertIn("source edit on main", self.sed("x.rs"))

    def test_edit_on_main_follows_doc_extensions(self) -> None:
        """Edit of x.rs is denied until .rs is declared a document extension, and .md loses its exemption on removal."""
        self.assertIn("source file", self.edit("x.rs"))
        self.assertEqual(self.edit("README.md"), "")
        data = json.loads(self.policy.read_text())
        self.edit_policy("doc_extensions", [*data["doc_extensions"], ".rs"])
        self.assertEqual(self.edit("x.rs"), "")
        self.edit_policy("doc_extensions", [e for e in data["doc_extensions"] if e != ".md"])
        self.assertIn("source file", self.edit("README.md"))

    def test_deleted_policy_fails_closed_on_main(self) -> None:
        """A missing file denies both gates on main with protected_paths_unreadable."""
        self.policy.unlink()
        self.assertIn("protected_paths_unreadable", self.sed("x.py"))
        self.assertIn("protected_paths_unreadable", self.edit("README.md"))
        subprocess.run(["git", "-C", str(self.repo), "symbolic-ref", "HEAD", "refs/heads/feature"], check=True)
        self.assertEqual(self.edit("README.md"), "")
        self.assertIn("settings", self.edit(".claude/settings.json").lower())


if __name__ == "__main__":
    unittest.main()
