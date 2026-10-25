"""Driver evidence remains bound to raw output and the worker checkout."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT / "packages/codex/skills/agentic-loop/scripts"))
import graph_driver_evidence  # noqa: E402
from graph_evidence import validate_worker_evidence  # noqa: E402


class DriverEvidenceTests(unittest.TestCase):
    """Use real files and a disposable Git repository for SHA revalidation."""

    def test_native_wave_history_survives_cutover(self) -> None:
        """Completion rejects a changed native wave outcome after the backup is sealed."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            old: dict[str, Any] = {
                "session_id": "S",
                "loop_id": "L",
                "revision": 1,
                "graph": {"nodes": {}, "dispatches": {}, "wave_history": {"wave-1": {"outcome": "failed"}}},
            }
            raw = json.dumps(old).encode()
            path.with_name("progress.json.pre-driver").write_bytes(raw)
            state = deepcopy(old)
            state["revision"] = 3
            state["graph"].update(native_last_revision=1, native_backup_sha256=hashlib.sha256(raw).hexdigest())
            graph_driver_evidence.validate_backup(path, state)
            state["graph"]["wave_history"]["wave-1"]["outcome"] = "done"
            with self.assertRaisesRegex(ValueError, "native wave history"):
                graph_driver_evidence.validate_backup(path, state)
            state["graph"]["wave_history"] = {}
            with self.assertRaisesRegex(ValueError, "native wave history"):
                graph_driver_evidence.validate_backup(path, state)

    def test_native_history_check_allows_pending_nodes_for_cutover(self) -> None:
        """Cutover rechecks past native evidence without requiring graph completion."""
        with patch("graph_evidence._stored_references", return_value=set()) as check:
            validate_worker_evidence({}, require_complete=False)
        check.assert_called_once_with({}, False)

    def fake_gh(self, base: Path, head: str) -> Callable[[str, str], None]:
        """Serve mutable PR responses from a disposable executable."""
        bin_dir = base / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"

        def serve(state: str, pr_head: str) -> None:
            response = json.dumps({"number": 42, "state": state, "headRefOid": pr_head})
            gh.write_text("#!/bin/sh\nprintf '%s\\n' '" + response + "'\n")
            gh.chmod(0o755)

        serve("OPEN", head)
        environment = patch.dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        environment.start()
        self.addCleanup(environment.stop)
        return serve

    def check_pr_revalidation(
        self,
        state_path: Path,
        state: dict[str, Any],
        ref: dict[str, Any],
        serve: Callable[[str, str], None],
        head: str,
        checkout: Path,
    ) -> None:
        """A closed or moved PR invalidates a sealed success; a merged one remains valid."""
        serve("CLOSED", head)
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
        serve("OPEN", "0" * len(head))
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
        serve("MERGED", head)
        graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
        serve("OPEN", head)
        dirty = checkout / "unpublished.txt"
        dirty.write_text("not in the PR")
        with self.assertRaisesRegex(ValueError, "clean"):
            graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
        dirty.unlink()

    def commit_empty(self, checkout: Path, message: str) -> None:
        """Advance the disposable worker checkout by one commit."""
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=t@example.test",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                message,
            ],
            check=True,
        )

    def test_publication_requires_clean_checkout_and_published_exact_head_pr(self) -> None:
        """A source worker can use an open or already merged PR at its HEAD."""
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            self.commit_empty(checkout, "first")
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            response = json.dumps({"number": 42, "state": "OPEN", "headRefOid": head})
            gh.write_text("#!/bin/sh\nprintf '%s\\n' '" + response + "'\n")
            gh.chmod(0o755)
            with patch.dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}"):
                self.assertEqual(graph_driver_evidence.publication(checkout), {"number": 42, "head": head})
                gh.write_text("#!/bin/sh\nprintf '%s\\n' '" + response.replace("OPEN", "MERGED") + "'\n")
                self.assertEqual(graph_driver_evidence.publication(checkout), {"number": 42, "head": head})
                graph_driver_evidence.validate_publication(checkout, 42, head)
                gh.write_text("#!/bin/sh\nprintf '%s\\n' '" + response.replace("OPEN", "CLOSED") + "'\n")
                with self.assertRaisesRegex(ValueError, "PR"):
                    graph_driver_evidence.publication(checkout)
                gh.write_text("#!/bin/sh\nprintf '%s\\n' '" + response.replace(head, "0" * len(head)) + "'\n")
                with self.assertRaisesRegex(ValueError, "HEAD"):
                    graph_driver_evidence.publication(checkout)
                (checkout / "uncommitted.txt").write_text("change")
                with self.assertRaisesRegex(ValueError, "clean"):
                    graph_driver_evidence.publication(checkout)

    def test_wiki_publication_requires_merged_head_on_origin_main(self) -> None:
        """A wiki update is done only after its exact commit lands upstream."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, checkout = base / "remote.git", base / "wiki"
            subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            self.commit_empty(checkout, "initial")
            subprocess.run(["git", "-C", str(checkout), "branch", "-M", "main"], check=True)
            subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", str(remote)], check=True)
            subprocess.run(["git", "-C", str(checkout), "push", "-q", "origin", "main"], check=True)
            subprocess.run(["git", "-C", str(checkout), "switch", "-q", "-c", "wiki-update"], check=True)
            self.commit_empty(checkout, "wiki update")
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            serve = self.fake_gh(base, head)
            self.assertTrue(graph_driver_evidence.needs_publication("S9-wiki", {"outcome": "done"}))
            self.assertFalse(graph_driver_evidence.needs_publication("S9-wiki", {"outcome": "skipped"}))
            serve("MERGED", head)
            with self.assertRaisesRegex(ValueError, "origin/main"):
                graph_driver_evidence.publication(checkout, require_merged=True)
            subprocess.run(["git", "-C", str(checkout), "push", "-q", "origin", "HEAD:main"], check=True)
            self.assertEqual(graph_driver_evidence.publication(checkout, require_merged=True)["head"], head)
            serve("OPEN", head)
            with self.assertRaisesRegex(ValueError, "merged"):
                graph_driver_evidence.publication(checkout, require_merged=True)
            self.commit_empty(checkout, "later wiki edit")
            later = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            serve("MERGED", later)
            with self.assertRaisesRegex(ValueError, "publication"):
                graph_driver_evidence.validate_publication(checkout, 42, head, require_merged=True, historical=True)

    def check_history(self, state_path: Path, state: dict[str, Any], ref: dict[str, Any]) -> None:
        """Check that each finished driver dispatch has one durable reference."""
        state["graph"]["nodes"] = {"U3[1]": {"evidence": ["native note", ref]}}
        state["graph"]["active_wave"] = None
        graph_driver_evidence.validate_history(state_path, state)
        foreign = deepcopy(state)
        foreign["graph"]["nodes"]["U3[1]"]["evidence"].append(ref)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            graph_driver_evidence.validate_history(state_path, foreign)
        foreign = deepcopy(state)
        foreign["graph"]["nodes"]["U3[1]"]["evidence"] = ["native note"]
        with self.assertRaisesRegex(ValueError, "missing"):
            graph_driver_evidence.validate_history(state_path, foreign)

    def check_backup(self, state_path: Path, state: dict[str, Any]) -> None:
        """A changed backup or native evidence prefix invalidates the cutover."""
        backup = state_path.with_name("progress.json.pre-driver")
        old = {
            "session_id": "S",
            "loop_id": "L",
            "revision": 1,
            "graph": {"nodes": {"U3[1]": {"evidence": ["native note"]}}, "dispatches": {}},
        }
        raw = json.dumps(old).encode()
        backup.write_bytes(raw)
        state["graph"]["native_backup_sha256"] = hashlib.sha256(raw).hexdigest()
        self.assertTrue(hasattr(graph_driver_evidence, "validate_backup"), "native backup validator is missing")
        graph_driver_evidence.validate_backup(state_path, state)
        backup.write_bytes(raw + b" ")
        with self.assertRaisesRegex(ValueError, "backup"):
            graph_driver_evidence.validate_backup(state_path, state)
        backup.write_bytes(raw)
        foreign = deepcopy(state)
        foreign["graph"]["nodes"]["U3[1]"]["evidence"][0] = "changed note"
        with self.assertRaisesRegex(ValueError, "native"):
            graph_driver_evidence.validate_backup(state_path, foreign)

    def check_failed_without_final(self, state_path: Path, state: dict[str, Any], checkout: Path) -> None:
        """A process failure can be sealed when Codex writes no final file."""
        failed_id = "disp_failed_attempt"
        original = state["graph"]["dispatches"]["disp_0123456789abcdef"]
        state["graph"]["dispatches"][failed_id] = deepcopy(original)
        artifact = state_path.parent / "driver-evidence" / failed_id
        artifact.mkdir()
        (artifact / "prompt.txt").write_text("build one unit\n")
        (artifact / "output.jsonl").write_text('{"type":"turn.failed"}\n')
        ref = graph_driver_evidence.seal(
            state_path,
            state,
            "U3[1]",
            failed_id,
            checkout,
            "codex",
            1,
            {"outcome": "failed", "evidence": "codex:process_exit_1"},
        )
        graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
        state["graph"]["dispatches"].pop(failed_id)

    def check_descendant_publication(
        self,
        base: Path,
        checkout: Path,
        state_path: Path,
        state: dict[str, Any],
        ref: dict[str, Any],
        head: str,
        serve: Callable[[str, str], None],
        output: Path,
    ) -> None:
        """Accept a verified descendant and reject changed or unrelated PR history."""
        remote = base / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        subprocess.run(["git", "-C", str(checkout), "remote", "add", "origin", str(remote)], check=True)
        subprocess.run(["git", "-C", str(checkout), "push", "-q", "origin", "HEAD:refs/pull/42/head"], check=True)
        self.check_history(state_path, state, ref)
        self.commit_empty(checkout, "published descendant")
        descendant = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
        subprocess.run(["git", "-C", str(checkout), "push", "-q", "origin", "HEAD:refs/pull/42/head"], check=True)
        subprocess.run(["git", "-C", str(checkout), "checkout", "-q", "--detach", head], check=True)
        serve("OPEN", descendant)
        graph_driver_evidence.validate_history(state_path, state)
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
        subprocess.run(["git", "-C", str(remote), "update-ref", "refs/pull/42/head", head], check=True)
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate_history(state_path, state)
        subprocess.run(["git", "-C", str(remote), "update-ref", "refs/pull/42/head", descendant], check=True)
        orphan = subprocess.check_output(
            ["git", "-C", str(checkout), "commit-tree", "4b825dc642cb6eb9a060e54bf8d69288fbee4904"],
            input="unrelated\n",
            text=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "t@example.test",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "t@example.test",
            },
        ).strip()
        subprocess.run(
            ["git", "-C", str(checkout), "push", "-q", "origin", f"{orphan}:refs/heads/unrelated"], check=True
        )
        subprocess.run(["git", "-C", str(remote), "update-ref", "refs/pull/42/head", orphan], check=True)
        serve("OPEN", orphan)
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate_history(state_path, state)
        subprocess.run(["git", "-C", str(remote), "update-ref", "refs/pull/42/head", descendant], check=True)
        serve("OPEN", "0" * len(head))
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate_history(state_path, state)
        serve("CLOSED", descendant)
        with self.assertRaisesRegex(ValueError, "publication"):
            graph_driver_evidence.validate_history(state_path, state)
        serve("OPEN", descendant)
        output.write_text('{"type":"turn.failed"}\n')
        with self.assertRaisesRegex(ValueError, "output"):
            graph_driver_evidence.validate_history(state_path, state)
        output.write_text('{"type":"turn.completed"}\n')

    def test_changed_output_or_head_invalidates_a_sealed_result(self) -> None:
        """A past pass cannot survive changed worker bytes or changed source."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            self.commit_empty(checkout, "first")
            state_path = base / "S" / "progress.json"
            state_path.parent.mkdir()
            dispatch_id = "disp_0123456789abcdef"
            state: dict[str, Any] = {
                "session_id": "S",
                "loop_id": "L",
                "graph": {
                    "dispatch_mode": "driver",
                    "driver_from_revision": 3,
                    "native_last_revision": 1,
                    "dispatches": {
                        dispatch_id: {
                            "node_id": "U3[1]",
                            "wave_id": "wave-3",
                            "revision": 3,
                            "attempt": 1,
                            "dispatch_mode": "driver",
                            "task_name": "worker_one",
                            "authorized": {
                                "driver_run_id": "run-1",
                                "prompt_sha256": hashlib.sha256(b"build one unit\n").hexdigest(),
                            },
                        }
                    },
                },
            }
            artifact = state_path.parent / "driver-evidence" / dispatch_id
            artifact.mkdir(parents=True)
            (artifact / "prompt.txt").write_text("build one unit\n")
            output = artifact / "output.jsonl"
            output.write_text('{"type":"turn.completed"}\n')
            final = artifact / "final.json"
            final.write_text('{"outcome":"done"}')
            with self.assertRaisesRegex(ValueError, "open or merged PR"):
                graph_driver_evidence.seal(
                    state_path, state, "U3[1]", dispatch_id, checkout, "codex", 0, {"outcome": "done"}
                )
            self.assertFalse((artifact / "manifest.json").exists())
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            serve = self.fake_gh(base, head)
            with patch.object(graph_driver_evidence, "publication", return_value={"number": 42, "head": head}):
                ref = graph_driver_evidence.seal(
                    state_path, state, "U3[1]", dispatch_id, checkout, "codex", 0, {"outcome": "done"}
                )
            graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
            self.check_pr_revalidation(state_path, state, ref, serve, head, checkout)
            self.check_failed_without_final(state_path, state, checkout)
            foreign = deepcopy(state)
            foreign["graph"]["dispatches"][dispatch_id]["authorized"]["prompt_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "prompt"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            self.check_descendant_publication(base, checkout, state_path, state, ref, head, serve, output)
            self.check_backup(state_path, state)
            foreign = deepcopy(state)
            foreign["graph"].pop("dispatch_mode")
            with self.assertRaisesRegex(ValueError, "cutover"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            foreign = deepcopy(state)
            foreign["graph"]["driver_from_revision"] = 4
            with self.assertRaisesRegex(ValueError, "cutover"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            with self.assertRaisesRegex(ValueError, "reference"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", {**ref, "extra": "accepted?"})
            output.write_text('{"type":"turn.failed"}\n')
            with self.assertRaisesRegex(ValueError, "output"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
            output.write_text('{"type":"turn.completed"}\n')
            final.write_text('{"outcome":"failed"}')
            with self.assertRaisesRegex(ValueError, "final"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
            final.write_text('{"outcome":"done"}')
            with self.assertRaisesRegex(ValueError, "already sealed"):
                graph_driver_evidence.seal(
                    state_path, state, "U3[1]", dispatch_id, checkout, "codex", 0, {"outcome": "done"}
                )
            with self.assertRaisesRegex(ValueError, "foreign"):
                graph_driver_evidence.validate(state_path, state, "U3[2]", ref)
            foreign = deepcopy(state)
            foreign["session_id"] = "other-session"
            with self.assertRaisesRegex(ValueError, "foreign"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            foreign = deepcopy(state)
            foreign["graph"]["dispatches"][dispatch_id]["attempt"] = 2
            with self.assertRaisesRegex(ValueError, "attempt"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            foreign = deepcopy(state)
            foreign["graph"]["dispatches"][dispatch_id]["authorized"]["driver_run_id"] = "other-run"
            with self.assertRaisesRegex(ValueError, "foreign"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            self.commit_empty(checkout, "second")
            with self.assertRaisesRegex(ValueError, "HEAD"):
                graph_driver_evidence.validate_history(state_path, state)


if __name__ == "__main__":
    unittest.main()
