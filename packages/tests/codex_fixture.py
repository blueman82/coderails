"""Build isolated current-schema native Codex graph and transcript fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import graph_contract
from graph_identity import GraphError, next_attempt, task_name

FINAL_REPORT: dict[str, Any] = {
    "claims": [{"text": "unit checks ran", "label": "verified", "source": "fixture command: OK"}],
    "did_not_verify": [],
}


def done_result(evidence: object = "checked") -> dict[str, Any]:
    """A `done` wave result carrying the final_report every begin-wave dispatch record requires."""
    return {"outcome": "done", "evidence": evidence, "final_report": FINAL_REPORT}


def node(number: int = 1, status: str = "pending") -> dict[str, Any]:
    """Return a canonical build-unit node."""
    return {
        "label": f"Build unit {number}",
        "status": status,
        "outcome": status,
        "retry": {"attempts": 0, "max": 2},
        "respawn": {"generation": 0, "intent": None},
        "evidence": [],
    }


def state() -> dict[str, Any]:
    """Return one independent current-schema build unit."""
    return {
        "schema_version": 3,
        "session_id": "parent",
        "loop_id": "loop",
        "revision": 1,
        "status": "in-progress",
        "created": "2026-10-24T10:00:00+00:00",
        "authorising_prompt_raw": "Run this bounded Codex graph test.",
        "state_minor": 3,
        "graph": {
            "nodes": {"U3[1]": node()},
            "edges": [],
            "joins": {},
            "active_wave": None,
            "hard_stop": None,
            "dispatches": {},
            "contract_from_revision": 1,
            "context_from_revision": 1,
        },
    }


def write_json(path: Path, value: object) -> None:
    """Write a JSON fixture."""
    path.write_text(json.dumps(value), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON fixture."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _completion(
    operation: str, path: Path, session: str, evals: Path, proof: Path, retro: Path, transcript: Path
) -> dict[str, Any]:
    """Run a separate Codex provider process so its D4 modules do not mix with Claude imports."""
    graph = Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts/graph.py"
    result = subprocess.run(
        [
            sys.executable,
            str(graph),
            operation,
            str(path),
            "--session",
            session,
            "--evals",
            str(evals),
            "--proof",
            str(proof),
            "--retro",
            str(retro),
            "--transcript",
            str(transcript),
        ],
        cwd=Path.home(),
        env={**os.environ, "HOME": str(Path.home())},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise GraphError(result.stderr.strip())
    return cast(dict[str, Any], json.loads(result.stdout))


def complete(path: Path, session: str, evals: Path, proof: Path, retro: Path, transcript: Path) -> dict[str, Any]:
    """Complete through the independent Codex CLI."""
    return _completion("complete", path, session, evals, proof, retro, transcript)


def verify_completion(
    path: Path, session: str, evals: Path, proof: Path, retro: Path, transcript: Path
) -> dict[str, Any]:
    """Verify through the independent Codex CLI."""
    return _completion("verify-completion", path, session, evals, proof, retro, transcript)


def frozen_evals() -> dict[str, Any]:
    """Return an ungraded session-bound dispatch suite."""
    return {
        "scope": "loop",
        "task_ref": "loop",
        "session_id": "parent",
        "loop_id": "loop",
        "verification_level": 1,
        "verification_justification": "native fixture",
        "frozen_sha": "fixture",
        "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
        "result": None,
        "grading": None,
    }


def append(path: Path, value: object) -> None:
    """Append a single native JSONL event."""
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value) + "\n")


def transcripts(home: Path) -> Path:
    """Create a unique native parent transcript."""
    directory = home / ".codex/sessions"
    directory.mkdir(parents=True)
    parent = directory / "fixture-parent.jsonl"
    append(parent, {"type": "session_meta", "payload": {"id": "parent"}})
    return parent


def dispatch_message(
    parent: Path, graph: dict[str, Any], node_id: str, task: str, state_path: Path | None = None
) -> str:
    """Render a fixture v2 message and consume its isolated begin-wave authorization."""
    records = graph["graph"].get("dispatches", {})
    issued = next(
        (
            (identifier, record)
            for identifier, record in records.items()
            if record["node_id"] == node_id and record["wave_id"] == graph["graph"]["active_wave"]["wave_id"]
        ),
        None,
    )
    message = "CODERAILS_GRAPH_TASK=" + task
    if issued is not None:
        identifier, record = issued
        message = (
            graph_contract.prompt_prefix(graph, identifier, record)
            + "\n"
            + graph_contract.render_sections(record["contract"])
            + "\nWorker instructions."
        )
        home = parent.parents[2]
        candidates: tuple[Path, ...]
        if state_path is not None:
            candidates = (state_path,)
        else:
            candidates = (
                home / "progress.json",
                home / "loops/project/parent/progress.json",
                home / "state/fixture" / graph["session_id"] / "progress.json",
            )
        matches: list[tuple[Path, dict[str, Any]]] = []
        for candidate in candidates:
            if not candidate.is_file():
                continue
            saved = read_json(candidate)
            if (
                saved.get("session_id") == graph["session_id"]
                and saved.get("loop_id") == graph["loop_id"]
                and saved["graph"]["active_wave"]["wave_id"] == record["wave_id"]
            ):
                matches.append((candidate, saved))
        if len(matches) != 1:
            raise AssertionError("fixture spawn requires one owned progress.json")
        state_path, saved = matches[0]
        saved["graph"]["dispatches"][identifier]["authorized"] = {"tool_use_id": f"call-{task}"}
        write_json(state_path, saved)
    return message


def spawn(
    parent: Path, graph: dict[str, Any], node_id: str = "U3[1]", terminal: bool = True, state_path: Path | None = None
) -> Path:
    """Append a native spawn and simulate the hook's prior consumption in the isolated fixture."""
    attempt = next_attempt(graph["graph"]["nodes"][node_id])
    task = task_name(graph["loop_id"], node_id, attempt)
    child_id = f"child-{task}"
    call_id = f"call-{task}"
    path = f"/root/{task}"
    message = dispatch_message(parent, graph, node_id, task, state_path)
    append(
        parent,
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "call_id": call_id,
                "arguments": json.dumps({"task_name": task, "message": message}),
            },
        },
    )
    append(
        parent,
        {
            "type": "event_msg",
            "payload": {
                "item": {
                    "type": "SubAgentActivity",
                    "kind": "started",
                    "id": call_id,
                    "agent_thread_id": child_id,
                    "agent_path": path,
                }
            },
        },
    )
    child = parent.parent / f"fixture-{child_id}.jsonl"
    metadata = {
        "id": child_id,
        "session_id": "parent",
        "parent_thread_id": "parent",
        "thread_source": "subagent",
        "source": {
            "subagent": {
                "thread_spawn": {"parent_thread_id": "parent", "depth": 1, "agent_role": None, "agent_path": path}
            }
        },
    }
    append(child, {"timestamp": "2026-09-21T00:00:01Z", "type": "session_meta", "payload": metadata})
    append(
        child,
        {
            "timestamp": "2026-09-21T00:00:02Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": f"turn-{task}"},
        },
    )
    if terminal:
        append(
            child,
            {
                "timestamp": "2026-09-21T00:00:03Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": f"turn-{task}"},
            },
        )
    return child


def refuse(
    parent: Path,
    graph: dict[str, Any],
    node_id: str = "U3[1]",
    call_id: str = "refused",
    result: str = "collab spawn failed: limit",
) -> str:
    """Append a native spawn_agent call answered by `result` (default an error) with no SubAgentActivity."""
    task = task_name(graph["loop_id"], node_id, next_attempt(graph["graph"]["nodes"][node_id]))
    call = {
        "type": "function_call",
        "name": "spawn_agent",
        "namespace": "collaboration",
        "call_id": f"{call_id}-{task}",
        "arguments": json.dumps({"task_name": task}),
    }
    append(parent, {"type": "response_item", "payload": call})
    output = {"type": "function_call_output", "call_id": call["call_id"], "output": result}
    append(parent, {"type": "response_item", "payload": output})
    return str(call["call_id"])
