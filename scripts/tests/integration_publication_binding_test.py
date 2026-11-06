"""Publication consumes the registered static manifest without freezing post-worker source HEAD."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
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


class PublicationCliBindingTests(unittest.TestCase):
    """Exercise both real push CLIs with local Git transport and only a gh transport stub."""

    def setUp(self) -> None:
        """Keep synthetic credentials, graph state, repositories and raw observations in scratch."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def git(self, checkout: Path, *arguments: str) -> str:
        """Run real Git against a disposable checkout or bare remote."""
        return subprocess.check_output(["git", "-C", str(checkout), *arguments], text=True, stderr=subprocess.PIPE)

    def fixture(self, provider: str, defect: str) -> tuple[Path, Path, Path, dict[str, str]]:
        """Create a separate repository and canonical graph binding for each control."""
        root = self.root / provider / defect
        checkout = root / "source"
        checkout.mkdir(parents=True)
        environment = dict(os.environ)
        session = f"fixture-{uuid.uuid4().hex}"
        environment.update(
            HOME=str(root / "home"),
            CODERAILS_PUBLICATION_SESSION_ID=session,
            CLAUDE_AGENTIC_LOOP_DIR=str(root / "loops"),
            CODERAILS_AGENTIC_LOOP_DIR=str(root / "loops"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
        )
        self.git(checkout, "init", "-q", "-b", "main")
        self.git(checkout, "config", "user.name", "Fixture")
        self.git(checkout, "config", "user.email", "fixture@test")
        initial = "outside.py" if defect == "rename-outside-to-allowed" else "allowed.py"
        (checkout / initial).write_text("before\n")
        if defect == "staged-outside":
            (checkout / "outside.py").write_text("outside before\n")
        self.git(checkout, "add", "--all")
        self.git(checkout, "commit", "-qm", "base")
        remote = root / "github.com/synthetic/fixture.git"
        remote.parent.mkdir(parents=True)
        self.git(checkout, "clone", "--bare", str(checkout), str(remote))
        self.git(checkout, "remote", "add", "origin", str(remote))
        self.git(checkout, "fetch", "-q", "origin")
        self.git(checkout, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.git(checkout, "switch", "-qc", "feature/unit")
        common = self.git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        progress = root / "loops" / common.replace("/", "-") / session / "progress.json"
        progress.parent.mkdir(parents=True)
        manifest = ["allowed.py", "renamed.py"] if defect == "valid-rename" else ["allowed.py"]
        unit = {"base_branch": "main", "manifest": manifest}
        unit.update(graph_source.source_assignment(str(checkout), manifest))
        progress.write_text(json.dumps({"session_id": session, "loop_id": session, "work_units": {"1": unit}}))
        binary = root / "bin"
        binary.mkdir()
        gh = binary / "gh"
        gh.write_text('#!/bin/sh\nif [ "$1 $2" = "pr create" ]; then echo "local-fixture-pr"; fi\n')
        gh.chmod(0o755)
        environment["PATH"] = str(binary) + os.pathsep + environment.get("PATH", "")
        if defect == "rename-outside-to-allowed":
            self.git(checkout, "mv", "outside.py", "allowed.py")
        elif defect == "rename-allowed-to-outside":
            self.git(checkout, "mv", "allowed.py", "outside.py")
        elif defect == "valid-rename":
            self.git(checkout, "mv", "allowed.py", "renamed.py")
        elif defect == "staged-outside":
            (checkout / "outside.py").write_text("outside after\n")
            self.git(checkout, "add", "outside.py")
        else:
            (checkout / "allowed.py").write_text("reviewed output\n")
        return checkout, remote, progress, environment

    def run_control(self, provider: str, defect: str) -> None:
        """Assert real commit/ref effects for a valid command and invalid graph bindings."""
        checkout, remote, progress, environment = self.fixture(provider, defect)
        state = json.loads(progress.read_text())
        selected = progress
        arguments = ["--unit", "1", "--progress", str(selected)]
        if defect in ("swap-progress", "relative-progress"):
            selected = (
                progress.parent / "copied-progress.json"
                if defect == "swap-progress"
                else Path(os.path.relpath(progress, checkout))
            )
            if defect == "swap-progress":
                selected.write_bytes(progress.read_bytes())
            arguments[-1] = str(selected)
        elif defect == "session":
            environment["CODERAILS_PUBLICATION_SESSION_ID"] = "another-session"
        elif defect == "missing-both":
            arguments = []
        elif defect in ("missing-unit", "missing-progress"):
            arguments = arguments[2:] if defect == "missing-unit" else arguments[:2]
        elif defect == "unit":
            arguments[1] = "2"
        elif defect == "worktree":
            state["work_units"]["1"]["worktree"] = str(self.root / "unassigned")
        elif defect == "manifest":
            state["work_units"]["1"]["manifest"] = ["**"]
        if defect in ("worktree", "manifest"):
            progress.write_text(json.dumps(state))
        before_head = self.git(checkout, "rev-parse", "HEAD")
        before_refs = self.git(remote, "show-ref")
        before_index = self.git(checkout, "write-tree")
        staged_before = self.git(checkout, "diff", "--cached", "--raw", "-z", "-M")
        if "rename" in defect:
            self.assertIn("R100", staged_before)
        script = ROOT / ("packages/codex/scripts/push.py" if provider == "codex" else "scripts/push.py")
        result = subprocess.run(
            [sys.executable, str(script), *arguments, "Local fixture publication"],
            cwd=checkout,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        observation = {
            "provider": provider,
            "defect": defect,
            "argv": result.args,
            "exit": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "head_before": before_head,
            "head_after": self.git(checkout, "rev-parse", "HEAD"),
            "refs_before": before_refs,
            "refs_after": self.git(remote, "show-ref"),
            "staged_before": staged_before,
        }
        evidence = os.environ.get("CODERAILS_PUBLICATION_TEST_LOG_DIR")
        if evidence:
            destination = Path(evidence)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / f"{provider}-{defect}.json").write_text(json.dumps(observation, indent=2))
        if defect in ("valid", "valid-rename"):
            self.assertEqual(result.returncode, 0, observation)
            self.assertNotEqual(observation["head_after"], before_head, observation)
            self.assertEqual(
                self.git(remote, "rev-parse", "refs/heads/feature/unit"), observation["head_after"], observation
            )
        else:
            self.assertNotEqual(result.returncode, 0, observation)
            reasons = {
                "worktree": "publication:worktree_invalid",
                "manifest": "publication:source_manifest_mismatch",
                "rename-outside-to-allowed": "diff_manifest:out_of_manifest",
                "rename-allowed-to-outside": "diff_manifest:out_of_manifest",
                "staged-outside": "diff_manifest:out_of_manifest",
            }
            reason = reasons.get(defect, "diff_manifest:manifest_unreadable")
            self.assertIn(reason, result.stderr, observation)
            self.assertEqual(observation["head_after"], before_head, observation)
            self.assertEqual(observation["refs_after"], before_refs, observation)
            self.assertEqual(self.git(checkout, "write-tree"), before_index, observation)

    def test_real_push_refuses_wrong_binding_before_commit_and_accepts_valid(self) -> None:
        """Invalid flags, ownership, path and static authority cannot mutate HEAD or remote refs."""
        for provider in ("claude", "codex"):
            for defect in (
                "valid",
                "valid-rename",
                "swap-progress",
                "relative-progress",
                "session",
                "missing-both",
                "missing-unit",
                "missing-progress",
                "unit",
                "worktree",
                "manifest",
                "rename-outside-to-allowed",
                "rename-allowed-to-outside",
                "staged-outside",
            ):
                with self.subTest(provider=provider, defect=defect):
                    self.run_control(provider, defect)


if __name__ == "__main__":
    unittest.main()
