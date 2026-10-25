"""`add-unit` contract flags are stored identically by both providers and reach the begin-wave contract."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
import graph_contract

from packages.tests.test_provider_controller_commands import ControllerCase


def assigned_checkout(root: Path) -> str:
    """Create a clean source checkout for a unit manifest."""
    worktree = root / "assigned"
    worktree.mkdir()
    subprocess.run(["git", "init", "-q", str(worktree)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "base",
        ],
        check=True,
    )
    return str(worktree.resolve())


class AddUnitContractTests(ControllerCase):
    """Only flags actually given are stored; a bad model role is a coded refusal that changes nothing."""

    def test_flags_are_stored_and_defaults_are_not(self) -> None:
        """--model-role, --write-scope, --lesson and --scope land on work_units[u]; absent flags add no keys."""
        for c in self.each():
            c.start()
            self.assertEqual(c.add("1").returncode, 0)
            worktree = assigned_checkout(c.root)
            result = c.add(
                "2",
                "--manifest",
                "src/**",
                "--worktree",
                worktree,
                "--model-role",
                "frontier",
                "--write-scope",
                "src/a.py",
                "--write-scope",
                "src/b.py",
                "--lesson",
                "read the spec",
                "--scope",
                "unit two",
                "--base-branch",
                "unit-one",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                c.read()["work_units"],
                {
                    "1": {"status": "pending"},
                    "2": {
                        "status": "pending",
                        "manifest": ["src/**"],
                        "worktree": worktree,
                        "source_manifest_sha256": graph_contract.source_binding(worktree, ["src/**"])[
                            "source_manifest_sha256"
                        ],
                        "model_role": "frontier",
                        "write_scope": ["src/a.py", "src/b.py"],
                        "lessons": ["read the spec"],
                        "scope": "unit two",
                        "base_branch": "unit-one",
                    },
                },
            )

    def test_bad_model_role_is_refused_with_a_code_and_no_write(self) -> None:
        """A model role outside the closed enum is refused before the lock, traced, and the state is untouched."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            result = c.add("1", "--model-role", "huge")
            self.refused(result, "add_unit_refused_bad_field")
            self.assertEqual(c.path.read_bytes(), before)
            self.assertEqual(c.codes("add-unit"), ["add_unit_refused_bad_field"])

    def test_bad_publication_base_is_refused_without_a_write(self) -> None:
        """A malformed remote branch cannot enter a unit record."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            result = c.add("1", "--base-branch", "../foreign")
            self.refused(result, "add_unit_refused_bad_field")
            self.assertEqual(c.path.read_bytes(), before)

    def test_worktree_is_stored_and_relative_path_is_refused(self) -> None:
        """A unit keeps its absolute checkout path; an invalid path cannot change the graph."""
        for c in self.each():
            c.start()
            worktree = str((c.root / "assigned").resolve())
            Path(worktree).mkdir()
            subprocess.run(["git", "init", "-q", worktree], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    worktree,
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@test",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "base",
                ],
                check=True,
            )
            result = c.add("1", "--worktree", worktree)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(c.read()["work_units"]["1"]["worktree"], worktree)
            before = c.path.read_bytes()
            result = c.add("2", "--worktree", "relative/path")
            self.refused(result, "add_unit_refused_bad_field")
            self.assertEqual(c.path.read_bytes(), before)

    def test_stored_inputs_and_defaults_reach_the_begin_wave_contract(self) -> None:
        """begin-wave renders the unit's inputs; unset inputs take the documented defaults (write_scope = manifest)."""
        for c in self.each():
            c.start()
            worktree = assigned_checkout(c.root)
            self.assertEqual(c.add("1", "--manifest", "src/**", "--worktree", worktree, "--lesson", "L1").returncode, 0)
            contract = graph_contract.build_contract(c.read(), "U3[1]", "main")
            self.assertEqual(
                (contract["role"], contract["manifest"], contract["write_scope"], contract["lessons"]),
                ("loop-worker", ["src/**"], ["src/**"], ["L1"]),
            )
            defaults = (contract["model_role"], contract["scope"], contract["disposition"])
            self.assertEqual(defaults, ("default", "", None))

    def test_manifest_requires_worktree_before_unit_registration(self) -> None:
        """A new source unit cannot enter the graph without an assigned checkout."""
        for c in self.each():
            c.start()
            before = c.path.read_bytes()
            self.refused(c.add("1", "--manifest", "src/**"), "add_unit_refused_bad_field")
            self.assertEqual(c.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
