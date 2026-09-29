"""Build isolated current-schema native Codex graph and transcript fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from graph_identity import next_attempt, task_name


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
        "graph": {"nodes": {"U3[1]": node()}, "edges": [], "joins": {}, "active_wave": None, "hard_stop": None},
    }


def write_json(path: Path, value: object) -> None:
    """Write a JSON fixture."""
    path.write_text(json.dumps(value), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    """Read a JSON fixture."""
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


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


def spawn(parent: Path, graph: dict[str, Any], node_id: str = "U3[1]", terminal: bool = True) -> Path:
    """Append a role-less provider-native spawn and its independently owned child."""
    attempt = next_attempt(graph["graph"]["nodes"][node_id])
    task = task_name(graph["loop_id"], node_id, attempt)
    child_id = f"child-{task}"
    call_id = f"call-{task}"
    path = f"/root/{task}"
    append(
        parent,
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "call_id": call_id,
                "arguments": json.dumps({"task_name": task}),
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
