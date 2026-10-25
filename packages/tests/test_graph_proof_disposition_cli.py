"""Check owner-only no-proof decisions through both provider CLIs."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.post_evals import grade_loop

ROOT = Path(__file__).resolve().parents[2]
GRAPHS = (
    ROOT / "skills/agentic-loop/scripts/graph.py",
    ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py",
)


class ProofDispositionCliTests(unittest.TestCase):
    """Exercise the two independently installed graph adapters."""

    def test_orders_source_ignores_completion_timestamp_only(self) -> None:
        """New receipts survive a new second; old same-second receipts stay valid."""
        self.assertEqual(
            (ROOT / "scripts/lib/orders_lifecycle.py").read_bytes(),
            (ROOT / "packages/codex/scripts/lib/orders_lifecycle.py").read_bytes(),
        )
        for source in (
            ROOT / "scripts/lib/orders_lifecycle.py",
            ROOT / "packages/codex/scripts/lib/orders_lifecycle.py",
        ):
            with self.subTest(provider=str(source)), tempfile.TemporaryDirectory() as temporary:
                lifecycle = runpy.run_path(str(source))
                initial = datetime(2026, 10, 25, tzinfo=timezone.utc)
                state: dict[str, Any] = {
                    "session_id": "session",
                    "loop_id": "loop",
                    "status": "in-progress",
                    "revision": 1,
                    "updated_at": initial.isoformat(timespec="seconds"),
                    "proof_disposition": "none: no executable surface",
                    "graph": {"nodes": {}},
                }
                state_dir = Path(temporary) / "session"
                state_dir.mkdir()
                progress = state_dir / "progress.json"
                progress.write_text(json.dumps(state), encoding="utf-8")
                normalized = lifecycle["source_state"](state)
                binding = {
                    "repo_dir": str(Path(temporary).resolve()),
                    "state_dir": str(state_dir.resolve()),
                    "session_id": "session",
                    "loop_id": "loop",
                    "revision": 1,
                    "progress_sha256": lifecycle["sha"](normalized),
                }
                legacy = binding | {
                    "progress_sha256": lifecycle["sha"](normalized | {"updated_at": state["updated_at"]})
                }
                receipt = lifecycle["preparation_path"](state_dir, "loop")
                receipt.write_text(json.dumps({"schema": 1, "binding": legacy, "records": []}), encoding="utf-8")
                lifecycle["prepared"](state_dir, binding, required=True)
                with self.assertRaisesRegex(ValueError, "order_source_mismatch"):
                    lifecycle["prepared"](state_dir, binding | {"revision": 2}, required=True)
                later = state | {"updated_at": (initial + timedelta(seconds=1)).isoformat(timespec="seconds")}
                progress.write_text(json.dumps(later), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "order_source_mismatch"):
                    lifecycle["prepared"](state_dir, binding, required=True)
                receipt.write_text(json.dumps({"schema": 1, "binding": binding, "records": []}), encoding="utf-8")
                lifecycle["prepared"](state_dir, binding, required=True)
                changed = later | {"proof_disposition": "none: different decision"}
                progress.write_text(json.dumps(changed), encoding="utf-8")
                changed_binding = binding | {"progress_sha256": lifecycle["sha"](lifecycle["source_state"](changed))}
                with self.assertRaisesRegex(ValueError, "order_source_mismatch"):
                    lifecycle["prepared"](state_dir, changed_binding, required=True)

    def test_owner_write_and_refusals(self) -> None:
        """Save one owned decision and reject invalid calls without a state write."""
        for graph in GRAPHS:
            with self.subTest(provider=str(graph)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                state = root / "session" / "progress.json"
                state.parent.mkdir()
                prompt = root / "prompt.txt"
                prompt.write_text("No executable surface", encoding="utf-8")

                def run(*args: str, graph_path: Path = graph) -> subprocess.CompletedProcess[str]:
                    return subprocess.run(
                        [sys.executable, str(graph_path), *args], capture_output=True, text=True, check=False
                    )

                started = run(
                    "start", str(state), "--session", "session", "--loop-id", "loop", "--prompt-file", str(prompt)
                )
                self.assertEqual(started.returncode, 0, started.stderr)

                def decision(
                    session: str = "session",
                    loop: str = "loop",
                    revision: int = 1,
                    disposition: str = "none",
                    reason: str = "no executable surface",
                    state_path: Path = state,
                ) -> subprocess.CompletedProcess[str]:
                    return run(
                        "record-proof-disposition",
                        str(state_path),
                        "--session",
                        session,
                        "--loop-id",
                        loop,
                        "--revision",
                        str(revision),
                        "--disposition",
                        disposition,
                        "--reason",
                        reason,
                    )

                invalid: tuple[dict[str, Any], ...] = (
                    {"session": "foreign"},
                    {"loop": "foreign"},
                    {"revision": 0},
                    {"disposition": "proofs"},
                    {"reason": " "},
                    {"reason": "none: false"},
                )
                for kwargs in invalid:
                    before = state.read_bytes()
                    refused = decision(**kwargs)
                    self.assertNotEqual(refused.returncode, 0, kwargs)
                    self.assertEqual(state.read_bytes(), before, kwargs)

                malformed = root / "malformed" / "progress.json"
                malformed.parent.mkdir()
                malformed.write_text("{bad json", encoding="utf-8")
                before = malformed.read_bytes()
                refused = decision(state_path=malformed)
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(malformed.read_bytes(), before)

                proof = state.with_name("proof.json")
                proof.write_text(json.dumps({"proofs": [{"cmd": "true", "status": "pending"}]}), encoding="utf-8")
                before = state.read_bytes()
                self.assertNotEqual(decision().returncode, 0)
                self.assertEqual(state.read_bytes(), before)
                proof.unlink()

                accepted = decision()
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertEqual(json.loads(state.read_text())["proof_disposition"], "none: no executable surface")
                self.assertFalse(proof.exists())
                self.assertNotEqual(decision().returncode, 0)
                trace = state.with_name("recovery-trace.jsonl").read_text(encoding="utf-8")
                self.assertIn('"command": "record-proof-disposition"', trace)
                self.assertIn('"outcome": "refused"', trace)
                self.assertIn('"outcome": "ok"', trace)

    def _completion_case(
        self, graph: Path, root: Path
    ) -> tuple[Callable[..., subprocess.CompletedProcess[str]], list[str], Path, Path]:
        """Build a fresh loop and its required non-proof completion artifacts."""
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        config = root / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("memory:\n  backend: off\n", encoding="utf-8")
        state = root / "loops/project/session/progress.json"
        state.parent.mkdir(parents=True)
        prompt = root / "prompt.txt"
        prompt.write_text("No executable surface", encoding="utf-8")
        if graph == GRAPHS[0]:
            transcript = root / ".claude/projects/project/session.jsonl"
            transcript_record = {
                "type": "user",
                "sessionId": "session",
                "uuid": "initial",
                "message": {"role": "user", "content": "No executable surface"},
            }
        else:
            transcript = root / ".codex/sessions/fixture-session.jsonl"
            transcript_record = {"type": "session_meta", "payload": {"id": "session"}}
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps(transcript_record) + "\n", encoding="utf-8")

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(graph), *args],
                cwd=root,
                env=os.environ | {"HOME": str(root), "CLAUDE_PROJECTS_DIR": str(root / ".claude/projects")},
                capture_output=True,
                text=True,
                check=False,
            )

        started = run("start", str(state), "--session", "session", "--loop-id", "loop", "--prompt-file", str(prompt))
        self.assertEqual(started.returncode, 0, started.stderr)
        recorded = run(
            "record-proof-disposition",
            str(state),
            "--session",
            "session",
            "--loop-id",
            "loop",
            "--revision",
            "1",
            "--disposition",
            "none",
            "--reason",
            "no executable surface",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stderr)
        suite: dict[str, Any] = {
            "schema_version": 1,
            "scope": "loop",
            "task_ref": "loop",
            "session_id": "session",
            "loop_id": "loop",
            "revision": 1,
            "verification_level": 0,
            "verification_justification": "No executable surface",
            "frozen_sha": "a" * 40,
            "head_sha": "a" * 40,
            "amendments": [],
            "evals": [],
        }
        evals = state.with_name("evals.json")
        evals.write_text(json.dumps(suite), encoding="utf-8")
        grade_loop(evals)
        retro = state.with_name("retro.json")
        retro.write_text(
            json.dumps({"schema_version": 1, "session_id": "session", "loop_id": "loop", "status": "complete"}),
            encoding="utf-8",
        )
        proof = state.with_name("proof.json")
        complete_args = ["complete", str(state), "--session", "session"]
        if graph == GRAPHS[1]:
            complete_args += [
                "--evals",
                str(evals),
                "--proof",
                str(proof),
                "--retro",
                str(retro),
                "--transcript",
                str(transcript),
            ]
        return run, complete_args, state, proof

    def test_cli_created_no_proof_loop_completes(self) -> None:
        """Run each provider's real completion command after a no-proof decision."""
        for graph in GRAPHS:
            with self.subTest(provider=str(graph)), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                run, complete_args, state, proof = self._completion_case(graph, root)
                proof.write_text(json.dumps({"proofs": [{"cmd": "true", "status": "pending"}]}), encoding="utf-8")
                before = state.read_bytes()
                self.assertNotEqual(run(*complete_args).returncode, 0)
                self.assertEqual(state.read_bytes(), before)
                if graph == GRAPHS[1]:
                    alternate = complete_args.copy()
                    alternate[alternate.index(str(proof))] = str(root / "missing-proof.json")
                    bypass = run(*alternate)
                    self.assertNotEqual(bypass.returncode, 0)
                    self.assertEqual(state.read_bytes(), before)
                proof.unlink()
                time.sleep(1.1)  # Cross the updated_at second before the real completion write.
                completed = run(*complete_args)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(json.loads(state.read_text())["status"], "complete")
                self.assertFalse(proof.exists())


if __name__ == "__main__":
    unittest.main()
