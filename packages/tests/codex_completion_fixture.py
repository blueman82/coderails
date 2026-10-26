"""Preserve completion-time evidence, revision, proof, and Stop-hook boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import graph_dispatch

from packages.tests.codex_fixture import (
    append,
    frozen_evals,
    read_json,
    spawn,
    state,
    transcripts,
    write_json,
)
from scripts.lib import orders_completion, retro, teardown_steps
from scripts.lib import proof_results as pr

IDENTITY = {"session_id": "parent", "loop_id": "loop"}


def assemble_test_retro(state_dir: Path, session: str) -> dict[str, Any]:
    """Build source-bound D4 preparation evidence for this isolated completion fixture."""
    path = state_dir / "progress.json"
    current: dict[str, Any] = read_json(path)
    loop_id = str(current.get("loop_id") or "")
    teardown_steps.record(
        state_dir, "proof_run", session, loop_id, teardown_steps.file_sha(state_dir / "proof_results.jsonl")
    )
    # A changed fixture source represents a new pre-preparation attempt.
    rows = teardown_steps.read_rows(state_dir)
    if current["status"] != "complete":
        rows = [row for row in rows if row["step"] not in {"orders_prepared", "retro_assembled"}]
        (state_dir / f"orders-prepared-{hashlib.sha256(loop_id.encode()).hexdigest()}.json").unlink(missing_ok=True)
    rank = {name: index for index, name in enumerate(teardown_steps.REQUIRED)}
    rows.sort(key=lambda row: rank.get(row["step"], len(rank)))
    (state_dir / teardown_steps.NAME).write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    retro.assemble(state_dir, session)  # explicit decision flush must precede preparation
    current = read_json(path)
    if current["status"] != "complete":
        orders_completion.prepare(path, session, loop_id)
    payload, code = retro.assemble(state_dir, session)
    if code == 2:
        raise AssertionError(payload)
    return read_json(state_dir / "retro.json")


class CompletionFixture(unittest.TestCase):
    """Build an isolated native Codex completion source."""

    def setUp(self) -> None:
        """Create a completed worker with independent proof and eval artifacts."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        previous = Path.cwd()
        subprocess.run(["git", "init", "-q", str(self.directory)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.directory),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "fixture",
            ],
            check=True,
        )
        config = self.directory / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("memory:\n  backend: off\n")
        os.chdir(self.directory)
        self.addCleanup(os.chdir, previous)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "loops/project/parent/progress.json"
        self.path.parent.mkdir(parents=True)
        write_json(self.path, state())
        self.evals = self.path.with_name("evals.json")
        write_json(self.evals, frozen_evals())
        parent = transcripts(self.directory)
        graph_dispatch.begin_wave(self.path)
        self.child = spawn(parent, read_json(self.path))
        graph_dispatch.record_wave(
            self.path,
            json.dumps({"wave_id": "wave-2", "results": {"U3[1]": {"outcome": "done", "evidence": "checked"}}}),
        )
        suite: dict[str, Any] = frozen_evals() | {
            "verification_level": 0,
            "revision": 3,
            "evals": [],
            "amendments": [],
            "result": "VERIFICATION_LEVEL0",
            "grading": {
                "by": "post_evals.py grade-loop",
                "checksum": hashlib.sha256(b"[]\nVERIFICATION_LEVEL0").hexdigest(),
                "amendments_at_grade": 0,
            },
        }
        write_json(self.evals, suite)
        self.proof, self.retro = self.path.with_name("proof.json"), self.path.with_name("retro.json")
        self.document: dict[str, Any] = {
            "schema_version": 2,
            "session_id": "parent",
            "loop_id": "loop",
            "proofs": [{"id": "P1", "cmd": "true", "expect": {"exit_code": 0}}],
        }
        write_json(self.proof, self.document)
        self.results = self.path.with_name(pr.RESULTS_NAME)
        pr.append(self.results, kind="freeze", proof_json_sha256=pr.doc_sha(self.document), **IDENTITY)
        self.proof_result("satisfied")
        assemble_test_retro(self.path.parent, "parent")
        self.transcript = self.path.with_name("proof.jsonl")
        append(self.transcript, {"type": "turn_context", "payload": {"loop_id": "loop"}})
        self.arguments = (self.path, "parent", self.evals, self.proof, self.retro, self.transcript)

    def proof_result(self, verdict: str, cmd: str = "true", **identity: str) -> None:
        """Append one controller run row for proof P1."""
        pr.append(
            self.results,
            kind="run",
            proof_id="P1",
            cmd_sha256=pr.sha(cmd),
            proof_json_sha256=pr.doc_sha(self.document),
            verdict=verdict,
            cwd=str(Path.cwd()),
            head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            source_tree_sha=subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
            **(IDENTITY | identity),
        )

    def decide(self, text: str = "adopt shape A", muninn: dict[str, Any] | None = None) -> None:
        """Put one hashed decision row into progress.json, then re-assemble the retro over it."""
        from scripts.lib import decision_record as dr

        current = read_json(self.path)
        added = dr.add_decision(current, "parent", "2.5", text, current["loop_id"], current["revision"])["state"]
        added["decisions_absorbed"][-1]["muninn"] = muninn or {"state": "written", "id": "K1", "reason_code": "ok"}
        write_json(self.path, added)
        if muninn and muninn.get("state") == "degraded":

            def store_unavailable(path: Path, session: str, **_kwargs: object) -> dict[str, Any]:
                decisions = read_json(path)["decisions_absorbed"]
                teardown_steps.record(
                    path.parent, "decisions_flushed", session, "loop", teardown_steps.sha_json(decisions)
                )
                return {"synced": [decisions[-1]], "exit_code": 3}

            with patch.object(dr, "flush_pending", side_effect=store_unavailable):
                assemble_test_retro(self.path.parent, "parent")
        else:
            assemble_test_retro(self.path.parent, "parent")
