"""Publication consumes the registered static manifest without freezing post-worker source HEAD."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_source  # noqa: E402

from scripts import push  # noqa: E402
from scripts.lib import git_common, manifest_policy  # noqa: E402


class PublicationBindingTests(unittest.TestCase):
    """Use local Git and the actual standalone/global publication preflights."""

    def setUp(self) -> None:
        """Create clean bound source and an owned graph outside its checkout."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.checkout = self.root / "source"
        self.checkout.mkdir()
        self.git("init", "-q", "-b", "feature/unit")
        self.git("remote", "add", "origin", "https://github.com/synthetic/repository.git")
        (self.checkout / "allowed.py").write_text("before\n")
        self.git("add", "allowed.py")
        self.commit()
        self.base = self.git("rev-parse", "HEAD").strip()
        self.unit: dict[str, Any] = {
            "manifest": ["allowed.py"],
            **graph_source.source_assignment(str(self.checkout), ["allowed.py"]),
        }
        common = self.git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        self.path = self.root / "loops" / common.replace("/", "-") / "owner" / "progress.json"
        self.path.parent.mkdir(parents=True)
        self.write()
        environment = patch.dict(
            os.environ,
            {
                "HOME": str(self.root / "home"),
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.root / "loops"),
                "CODERAILS_PUBLICATION_SESSION_ID": "owner",
            },
        )
        environment.start()
        self.addCleanup(environment.stop)
        previous = Path.cwd()
        os.chdir(self.checkout)
        self.addCleanup(os.chdir, previous)

    def git(self, *args: str) -> str:
        """Run only a local synthetic Git command."""
        return subprocess.check_output(["git", "-C", str(self.checkout), *args], text=True, stderr=subprocess.PIPE)

    def commit(self) -> None:
        """Advance the trusted root destination with a normal local commit."""
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@test", "commit", "-qm", "root change")

    def write(self) -> None:
        """Replace only this synthetic unit state."""
        self.path.write_text(json.dumps({"session_id": "owner", "loop_id": "loop", "work_units": {"1": self.unit}}))

    def test_unchanged_manifest_allows_dirty_source_and_later_root_commit(self) -> None:
        """The static binding remains valid after worker materialization and root publication."""
        for committed in (False, True):
            (self.checkout / "allowed.py").write_text("root reviewed output\n")
            if committed:
                self.git("add", "allowed.py")
                self.commit()
            scoped = push.unit_manifest("1", str(self.path))
            self.assertIsNotNone(scoped)
            assert scoped is not None
            self.assertEqual(scoped[0], ["allowed.py"])
            self.assertEqual(manifest_policy.unit_manifest(str(self.path), "1"), ["allowed.py"])
        self.assertEqual(manifest_policy.violations(unit="1", progress=str(self.path), base=self.base), [])

    def test_both_preflights_refuse_widened_or_missing_static_binding(self) -> None:
        """A manifest edit cannot become publication authority by retaining or deleting its hash."""
        original = dict(self.unit)
        for defect in ("widen", "missing", "hash"):
            self.unit = dict(original)
            if defect == "widen":
                self.unit["manifest"] = ["**"]
            elif defect == "missing":
                del self.unit["source_manifest_sha256"]
            else:
                self.unit["source_manifest_sha256"] = "0" * 64
            self.write()
            with self.subTest(defect=defect), self.assertRaises(git_common.WorkflowError):
                push.unit_manifest("1", str(self.path))
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                manifest_policy.unit_manifest(str(self.path), "1")

    def test_actual_global_gate_refuses_widening_for_outside_change(self) -> None:
        """The global consumer rejects stale scope before it can authorize the outside path."""
        (self.checkout / "outside.py").write_text("outside original unit\n")
        self.git("add", "outside.py")
        self.commit()
        self.unit["manifest"] = ["**"]
        self.write()
        found = manifest_policy.violations(unit="1", progress=str(self.path), base=self.base)
        self.assertEqual([row["code"] for row in found], ["diff_manifest:manifest_unreadable"])


if __name__ == "__main__":
    unittest.main()
