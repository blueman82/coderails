"""Isolated current-schema fixtures shaped like native Claude CLI transcripts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def write_json(path: Path, value: object) -> None:
    """Write a fixture object without shell interpolation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def append(path: Path, value: object) -> None:
    """Append one synthetic unit-test record, distinct from live CLI evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as output:
        output.write(json.dumps(value) + "\n")


def state(count: int = 1) -> dict[str, Any]:
    """Return independent build nodes with current registry labels."""
    nodes: dict[str, Any] = {
        f"U3[{number}]": {
            "label": f"Build unit {number}",
            "status": "pending",
            "outcome": "pending",
            "retry": {"attempts": 0, "max": 5},
            "respawn": {"generation": 0, "intent": None},
            "evidence": [],
        }
        for number in range(1, count + 1)
    }
    return {
        "schema_version": 3,
        "session_id": "fixture-session",
        "loop_id": "fixture-loop",
        "revision": 1,
        "status": "in-progress",
        "work_units": {},
        "graph": {"nodes": nodes, "edges": [], "joins": {}, "active_wave": None, "hard_stop": None},
    }


def frozen_evals() -> dict[str, Any]:
    """Provide an ungraded suite with the current stable loop identity."""
    return {
        "scope": "loop",
        "session_id": "fixture-session",
        "loop_id": "fixture-loop",
        "revision": 1,
        "verification_level": 2,
        "verification_justification": "Native contract tests",
        "frozen_sha": "a" * 40,
        "evals": [{"id": "E1", "mode": "agent-run", "priority": "P0", "status": "pending", "evidence": ""}],
    }


def parent(home: Path) -> Path:
    """Create a fixture at the actual provider-owned transcript path shape."""
    path = home / ".claude/projects/project/fixture-session.jsonl"
    append(
        path,
        {
            "type": "user",
            "sessionId": "fixture-session",
            "uuid": "initial",
            "message": {"role": "user", "content": "Fixture start"},
        },
    )
    return path


def spawn(
    path: Path,
    graph: dict[str, Any],
    node: str,
    *,
    role: str = "general-purpose",
    completed: bool = True,
    suffix: str = "",
    mailbox: bool = False,
) -> tuple[str, str]:
    """Emit a native request, result and child; optionally emit a successful terminal."""
    session = graph["session_id"]
    wave = graph["graph"]["active_wave"]["wave_id"]
    tag = re.sub(r"[^A-Za-z0-9_-]", "_", node.replace("[", "_").replace("]", "")) + "_" + wave + suffix
    tool, agent = "toolu_" + tag, "agent_" + tag
    ownership = {key: graph[key] for key in ("session_id", "loop_id", "revision")}
    ownership.update({"wave_id": wave, "node_id": node})
    prompt = (
        "CODERAILS_GRAPH_DISPATCH=" + json.dumps(ownership) + "\nRead the worker instructions and execute this unit."
    )
    append(
        path,
        {
            "type": "assistant",
            "sessionId": session,
            "isSidechain": False,
            "uuid": "spawn_" + tag,
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Agent",
                        "id": tool,
                        "input": {"subagent_type": role, "prompt": prompt},
                    }
                ]
            },
        },
    )
    append(
        path,
        {
            "type": "user",
            "sessionId": session,
            "isSidechain": False,
            "message": {"content": [{"type": "tool_result", "tool_use_id": tool}]},
            "toolUseResult": {"status": "teammate_spawned" if mailbox else "async_launched", "agentId": agent},
        },
    )
    child = path.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"
    common = {"sessionId": session, "isSidechain": True, "agentId": agent}
    append(child, {**common, "type": "user", "message": {"role": "user", "content": prompt}})
    if completed:
        append(
            child,
            {
                **common,
                "type": "assistant",
                "attributionAgent": role,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Worker complete"}],
                    "stop_reason": "end_turn",
                },
            },
        )
        notify(path, tool, agent)
    return tool, agent


def notify(path: Path, tool: str, agent: str, status: str = "completed", result: str = "Worker complete") -> None:
    """Append a harness-shaped terminal notification for a fixture child."""
    text = (
        f"<task-notification><tool-use-id>{tool}</tool-use-id><task-id>{agent}</task-id>"
        f"<status>{status}</status><result>{result}</result></task-notification>"
    )
    append(path, {"type": "queue-operation", "operation": "enqueue", "sessionId": "fixture-session", "content": text})


def report(graph: dict[str, Any], outcome: str = "done") -> dict[str, Any]:
    """Build a whole-wave result with no caller-provided native provenance."""
    wave = graph["graph"]["active_wave"]
    results: dict[str, Any] = {
        node: {"outcome": outcome, "evidence": "Focused behavior checks executed"} for node in wave["nodes"]
    }
    if outcome == "stale":
        for result in results.values():
            result["stale_check"] = {"checked": True, "method": "inspect native child", "result": "no terminal"}
    return {"wave_id": wave["wave_id"], "results": results}
