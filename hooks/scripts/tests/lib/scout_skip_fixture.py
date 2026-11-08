"""Private synthetic transcripts for public scout-wave consumer tests."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[4]
REASONS = {"S2.5": "no_design_fork: no unresolved design choice", "S2.6": "no_retired_path: no retired path"}
ROLES = {"S2.5": "design-scout", "S2.6": "disposition-scout"}


def node(label: str) -> dict[str, Any]:
    """Return a hand-authored registry-labelled pending node."""
    return {
        "label": label,
        "status": "pending",
        "outcome": "pending",
        "retry": {"attempts": 0, "max": 5},
        "respawn": {"generation": 0, "intent": None},
        "evidence": [],
    }


class ScoutFixture:
    """Drive production CLIs in a private HOME without native launches or provider calls."""

    def __init__(self, provider: str) -> None:
        """Issue an independent two-scout wave through the provider CLI."""
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.provider = provider
        self.home = self.directory / "home"
        self.home.mkdir()
        self.path = self.directory / "progress.json"
        self.environment = {
            "HOME": str(self.home),
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(ROOT),
            "CLAUDE_PROJECTS_DIR": str(self.home / ".claude/projects"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.home / "state"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.home / "state"),
            "CLAUDE_DISCIPLINE_LOG": str(self.home / "discipline.log"),
            "CODERAILS_A6_EVIDENCE_WRITE": "on",
        }
        source = "skills/agentic-loop/scripts/graph.py"
        self.cli = ROOT / (source if provider == "claude" else "packages/codex/" + source)
        self.transcript = self.home / (
            ".claude/projects/project/parent.jsonl" if provider == "claude" else ".codex/sessions/fixture-parent.jsonl"
        )
        self.transcript.parent.mkdir(parents=True)
        self.append(
            {"type": "user", "sessionId": "parent", "uuid": "initial", "message": {"role": "user", "content": "start"}}
            if provider == "claude"
            else {"type": "session_meta", "payload": {"id": "parent"}}
        )
        self.initial: dict[str, Any] = {
            "schema_version": 3,
            "state_minor": 2,
            "session_id": "parent",
            "loop_id": "loop",
            "revision": 1,
            "status": "in-progress",
            "work_units": {},
            "graph": {
                "nodes": {
                    "S2.5": node("Resolve design fork"),
                    "S2.6": node("Choose disposition"),
                    "J2": node("Preflight decisions joined"),
                },
                "edges": [{"from": "S2.5", "to": "J2"}, {"from": "S2.6", "to": "J2"}],
                "joins": {"J2": {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"], "released": False}},
                "active_wave": None,
                "hard_stop": None,
                "dispatches": {},
                "contract_from_revision": 1,
            },
        }
        self.save(self.initial)
        self.path.with_name("evals.json").write_text(
            json.dumps(
                {
                    "scope": "loop",
                    "task_ref": "loop",
                    "session_id": "parent",
                    "loop_id": "loop",
                    "verification_level": 1,
                    "verification_justification": "Synthetic dispatch prerequisite, not acceptance evidence",
                    "frozen_sha": "fixture-sha",
                    "evals": [{"id": "fixture", "mode": "agent-run", "priority": "P0", "status": "pending"}],
                }
            )
        )
        self.opened = self.accept("begin-wave", str(self.path))
        self.baseline = self.load()
        self.initial_transcript = self.transcript.read_bytes()

    def close(self) -> None:
        """Remove only this test's disposable files."""
        self.temporary.cleanup()

    def save(self, state: dict[str, Any]) -> None:
        """Persist an explicit input fixture outside production transitions."""
        self.path.write_text(json.dumps(state) + "\n")

    def load(self) -> dict[str, Any]:
        """Read actual persisted output without a production oracle."""
        return cast(dict[str, Any], json.loads(self.path.read_text()))

    def reset(self) -> dict[str, Any]:
        """Restore byte-equivalent issued input and its no-work transcript."""
        self.transcript.write_bytes(self.initial_transcript)
        state = copy.deepcopy(self.baseline)
        self.save(state)
        return state

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the actual public graph CLI, retaining ordinary return status."""
        return subprocess.run(
            [sys.executable, str(self.cli), *args],
            cwd=ROOT,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def accept(self, *args: str) -> dict[str, Any]:
        """Require a successful prerequisite so instrument failures cannot pass a test."""
        result = self.run(*args)
        if result.returncode:
            raise AssertionError(f"fixture command failed: {args!r}\n{result.stdout}\n{result.stderr}")
        return cast(dict[str, Any], json.loads(result.stdout))

    def report(self) -> dict[str, Any]:
        """Use literal no-work reasons for the actual current ready wave."""
        wave = self.load()["graph"]["active_wave"]
        return {
            "wave_id": wave["wave_id"],
            "results": {key: {"outcome": "skipped", "evidence": REASONS[key]} for key in wave["nodes"]},
        }

    def record(self, report: dict[str, Any] | None = None) -> subprocess.CompletedProcess[str]:
        """Invoke the actual save boundary with the complete active-wave report."""
        return self.run("record-wave", str(self.path), json.dumps(self.report() if report is None else report))

    def append(self, row: dict[str, Any]) -> None:
        """Append a synthetic provider-shaped event, never a live provider record."""
        with self.transcript.open("a") as handle:
            handle.write(json.dumps(row) + "\n")

    def consume(self, node_id: str, tool_use_id: str = "") -> None:
        """Exercise real single-use authorization without performing its native launch."""
        item = next(item for item in self.opened["dispatches"] if item["node_id"] == node_id)
        prompt = item["prompt_prefix"] + "\n" + item["prompt_sections"] + "\nRead scout instructions."
        args = [
            "authorize-dispatch",
            str(self.path),
            "--session",
            "parent",
            "--tool-use-id",
            tool_use_id or "call-" + node_id,
        ]
        if self.provider == "claude":
            args.extend(["--prompt", prompt, "--subagent-type", "coderails:" + ROLES[node_id]])
        else:
            message = self.directory / "message.txt"
            message.write_text(prompt)
            args.extend(
                [
                    "--dispatch-id",
                    item["dispatch_id"],
                    "--message-file",
                    str(message),
                    "--agent-type",
                    ROLES[node_id],
                    "--task-name",
                    item["task_name"],
                ]
            )
        self.accept(*args)

    def revalidate(self) -> subprocess.CompletedProcess[str]:
        """Call production evidence revalidation when artifact gates prevent full completion."""
        if self.provider == "claude":
            code = (
                "import json,sys; from hooks.scripts.lib.graph_evidence_revalidate import revalidate_all; "
                "revalidate_all(json.load(open(sys.argv[1]))); print('accepted')"
            )
        else:
            code = (
                "import json,sys; sys.path.insert(0,sys.argv[2]); "
                "from graph_evidence import validate_worker_evidence; "
                "validate_worker_evidence(json.load(open(sys.argv[1]))); print('accepted')"
            )
        return subprocess.run(
            [sys.executable, "-c", code, str(self.path), str(ROOT / "packages/codex/skills/agentic-loop/scripts")],
            cwd=ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def raw_codex_call(self, node_id: str, kind: str, loop_id: str = "loop") -> None:
        """Describe an unresolved or ambiguous raw request independently of production indexes."""
        task = "loop_worker_" + loop_id.encode().hex() + "_" + node_id.encode().hex()
        if kind in {"other-attempt", "other-attempt-start"}:
            task += "_a2"
        self.append(
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "spawn_agent",
                    "namespace": "collaboration",
                    "call_id": "raw-call",
                    "arguments": json.dumps({"task_name": task}),
                },
            }
        )
        if kind in {"duplicate-activity", "other-attempt-start"}:
            activity = {
                "type": "event_msg",
                "payload": {
                    "item": {
                        "type": "SubAgentActivity",
                        "kind": "started",
                        "id": "raw-call",
                        "agent_thread_id": "unstarted-fixture-child",
                        "agent_path": "/root/" + task,
                    }
                },
            }
            self.append(activity)
            if kind == "duplicate-activity":
                self.append(activity)
