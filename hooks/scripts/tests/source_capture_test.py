"""Immutable source proposals are raw bytes, scoped and independent of worker Git."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hooks.scripts.tests import driver_workspace_test as fixture
from scripts.sandbox import source_capture as capture


class CaptureTests(unittest.TestCase):
    """All repositories, credentials and escape targets are disposable synthetic fixtures."""

    def setUp(self) -> None:
        """SetUp."""
        self.context = fixture.WorkspaceTests("test_preparation_is_owned_idempotent_and_leaves_destination_clean")
        self.context.setUp()
        self.addCleanup(self.context.doCleanups)

    def workspace(self, *, tracked: bool = False) -> dict[str, Any]:
        """Optionally put a trusted regular baseline file in D before preparing C."""
        if tracked:
            (self.context.destination / "allowed.txt").write_bytes(b"baseline")
            capture.git("-C", str(self.context.destination), "add", "allowed.txt")
            capture.git(
                "-C",
                str(self.context.destination),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=t@example.invalid",
                "commit",
                "-qm",
                "baseline",
            )
        return self.context.prepare()

    def freeze(self, workspace: dict[str, Any]) -> dict[str, Any]:
        """Exercise the actual fixed-tree policy consumer."""
        self.assertTrue(hasattr(capture, "freeze"), "immutable source capture is not implemented")
        return capture.freeze(
            Path(str(workspace["execution"])),
            Path(str(workspace["store"])),
            str(workspace["head"]),
            ["allowed.txt"],
            ["allowed.txt"],
            "synthetic-dedicated-secret",
        )

    def test_binary_untracked_proposal_is_fixed_after_worker_changes(self) -> None:
        """Binary untracked proposal is fixed after worker changes."""
        workspace = self.workspace()
        clone, store = Path(str(workspace["execution"])), Path(str(workspace["store"]))
        payload = b"\0untracked\xff\r\n"
        (clone / "allowed.txt").write_bytes(payload)
        proposal = self.freeze(workspace)
        (clone / "allowed.txt").write_bytes(b"later writer")
        mode, oid = capture.tree_entries(store, str(proposal["tree"]))["allowed.txt"]
        self.assertEqual(mode, "100644")
        self.assertEqual(capture.blob(store, oid), payload)

    def test_deletion_is_explicit_against_trusted_baseline(self) -> None:
        """Deletion is explicit against trusted baseline."""
        workspace = self.workspace(tracked=True)
        Path(str(workspace["execution"]), "allowed.txt").unlink()
        proposal = self.freeze(workspace)
        self.assertEqual(capture.tree_entries(Path(str(workspace["store"])), str(proposal["tree"])), {})

    def test_trusted_ignore_allows_cache_but_worker_ignore_cannot_hide_source(self) -> None:
        """Trusted ignore allows cache but worker ignore cannot hide source."""
        destination = self.context.destination
        (destination / ".gitignore").write_text("cache/\n")
        capture.git("-C", str(destination), "add", ".gitignore")
        capture.git(
            "-C",
            str(destination),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-qm",
            "ignore",
        )
        workspace = self.workspace()
        clone = Path(str(workspace["execution"]))
        (clone / "allowed.txt").write_bytes(b"proposal")
        cache = clone / "cache"
        cache.mkdir()
        (cache / "linked-product").symlink_to(destination)
        proposal = self.freeze(workspace)
        self.assertIn("cache/", proposal["excluded"])
        self.assertEqual(
            capture.tree_entries(Path(str(workspace["store"])), str(proposal["tree"]))["allowed.txt"][0], "100644"
        )
        (clone / ".gitignore").write_text("cache/\noutside.txt\n")
        (clone / "outside.txt").write_text("cannot hide")
        with self.assertRaisesRegex(ValueError, "scope"):
            capture.freeze(
                clone,
                Path(str(workspace["store"])),
                str(workspace["head"]),
                ["allowed.txt", ".gitignore"],
                ["allowed.txt", ".gitignore"],
                "synthetic",
            )

    def test_trusted_control_parents_survive_but_new_controls_and_type_changes_refuse(self) -> None:
        """Tracked provider directories are baseline parents, never permission for new controls."""
        destination = self.context.destination
        for relative in (".claude/skills/x.md", ".codex/agents/x.md"):
            leaf = destination / relative
            leaf.parent.mkdir(parents=True)
            leaf.write_text("trusted baseline")
        capture.git("-C", str(destination), "add", ".claude", ".codex")
        capture.git(
            "-C",
            str(destination),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-qm",
            "tracked provider controls",
        )
        workspace = self.workspace()
        clone, store = Path(str(workspace["execution"])), Path(str(workspace["store"]))
        proposal = self.freeze(workspace)
        self.assertEqual(proposal["tree"], workspace["baseline_tree"])
        self.assertEqual(
            capture.tree_entries(store, str(proposal["tree"])),
            capture.tree_entries(store, str(workspace["head"])),
        )
        for relative in (".claude/skills/new.md", ".codex/agents/new.md"):
            new = clone / relative
            new.write_text("new control")
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "control_path"):
                self.freeze(workspace)
            new.unlink()
        (clone / ".claude/skills/x.md").unlink()
        (clone / ".claude/skills").rmdir()
        (clone / ".claude").rmdir()
        (clone / ".claude").symlink_to(destination / ".claude", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "control_path"):
            self.freeze(workspace)
        (clone / ".claude").unlink()
        (clone / ".claude").write_text("replacement regular file")
        with self.assertRaisesRegex(ValueError, "control_path"):
            capture.freeze(clone, store, str(workspace["head"]), ["**"], ["**"], "synthetic")

    def test_scope_secret_symlink_hardlink_mode_and_bound_refuse(self) -> None:
        """Scope secret symlink hardlink mode and bound refuse."""
        workspace = self.workspace(tracked=True)
        clone = Path(str(workspace["execution"]))
        target = clone / "allowed.txt"
        (clone / "outside.txt").write_text("out of scope")
        with self.assertRaisesRegex(ValueError, "scope"):
            self.freeze(workspace)
        (clone / "outside.txt").unlink()
        target.write_text("synthetic-dedicated-secret")
        with self.assertRaisesRegex(ValueError, "secret"):
            self.freeze(workspace)
        target.unlink()
        target.symlink_to(self.context.destination / "allowed.txt")
        with self.assertRaisesRegex(ValueError, "type"):
            self.freeze(workspace)
        target.unlink()
        os.link(self.context.destination / "allowed.txt", target)
        with self.assertRaisesRegex(ValueError, "hardlink"):
            self.freeze(workspace)
        target.unlink()
        target.write_bytes(b"changed")
        target.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "scope"):
            self.freeze(workspace)
        target.chmod(0o644)
        with patch.object(capture, "MAX_FILE_BYTES", 1), self.assertRaisesRegex(ValueError, "bound"):
            self.freeze(workspace)


if __name__ == "__main__":
    unittest.main()
